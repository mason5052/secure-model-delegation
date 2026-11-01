from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import httpx

from smd_app.engine import default_policy
from smd_app.evaluation import canonical
from smd_app.providers import ProviderRegistry

SPEC = importlib.util.spec_from_file_location('external_diagnostic', Path(__file__).parents[1] / 'scripts/run_external_model_diagnostic.py')
diag = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diag
SPEC.loader.exec_module(diag)


def approved(path, **overrides):
    value = {'approved':True,'provider':'openai','model':diag.MODEL,'max_attempts':25,'max_cost_usd':'1.00','endpoint':diag.ENDPOINT,'data_scope':diag.SCOPE,'pricing_usd_per_million':{'input':'0.75','output':'4.50'},'approval_reference':'Synthetic test approval only'}
    value.update(overrides)
    path.write_text(json.dumps(value))
    return diag.Approval.read(path)


class ApprovalAndBudgetTests(unittest.TestCase):
    def test_approval_rejects_unapproved_scope_model_endpoint_and_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'approval.json'
            for override in [{'approved':False},{'model':'unpinned'},{'endpoint':'http://127.0.0.1/v1/chat/completions'},{'max_attempts':26},{'max_cost_usd':'1.01'},{'data_scope':'raw_work_prompts'}]:
                with self.assertRaises(ValueError):approved(path,**override)

    def test_attempt_cap_persists_and_unknown_delivery_retains_full_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            approval=approved(Path(directory)/'approval.json',max_attempts=1)
            ledger=diag.BudgetLedger(approval)
            entry=ledger.reserve('first')
            reserve=ledger.total
            ledger.finish(entry,'unknown',None)
            self.assertEqual(ledger.total,reserve)
            ledger.close()
            reopened=diag.BudgetLedger(approval)
            try:
                with self.assertRaises(ValueError):reopened.reserve('second')
            finally:reopened.close()

    def test_cost_is_reserved_before_dispatch_and_parallel_ledger_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            approval=approved(Path(directory)/'approval.json',max_cost_usd='0.01')
            ledger=diag.BudgetLedger(approval)
            try:
                with self.assertRaises(ValueError):ledger.reserve('too_expensive')
                with self.assertRaises(FileExistsError):diag.BudgetLedger(approval)
                self.assertEqual(ledger.data['attempts'],[])
            finally:ledger.close()


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_adapter_body_and_response_saved_without_auth_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ledger=diag.BudgetLedger(approved(root/'approval.json'))
            key='synthetic-only-secret-key'
            called=[]
            def handler(request):
                called.append(request)
                body=json.loads(request.content)
                self.assertEqual(str(request.url),diag.ENDPOINT)
                self.assertEqual(body['model'],diag.MODEL)
                self.assertIs(body['store'],False)
                self.assertEqual(body['reasoning_effort'],'none')
                return httpx.Response(200,headers={'x-request-id':'req_synthetic'},json={'id':'chatcmpl-synthetic','choices':[{'message':{'role':'assistant','content':'{"status":"ready"}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':31,'completion_tokens':7}})
            transport=diag.ApprovedTransport(root,ledger,delegate=httpx.MockTransport(handler))
            registry=ProviderRegistry(transport=transport);registry.configure('openai',key,diag.MODEL)
            try:
                result=await diag.dispatch(registry,transport,'probe',[{'role':'user','content':'Fictional public test.'}],{'quality':{'type':'json_fields','expected':{'status':'ready'}}})
                self.assertTrue(result['quality']['success'])
                self.assertEqual(len(called),1)
                record=transport.records[0]
                self.assertEqual((root/record['request_body_path']).read_bytes(),called[0].content)
                self.assertEqual(record['provider_request_id'],'req_synthetic')
                for path in root.rglob('*'):
                    if path.is_file():self.assertNotIn(key.encode(),path.read_bytes())
            finally:ledger.close()

    async def test_endpoint_settings_and_fixture_guard_precede_any_dispatch_or_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ledger=diag.BudgetLedger(approved(root/'approval.json'))
            def never(request):self.fail('A rejected request must not dispatch.')
            transport=diag.ApprovedTransport(root,ledger,delegate=httpx.MockTransport(never))
            transport.expected_messages=[{'role':'user','content':'Fictional protected fixture alpha-hidden-value.'}]
            transport.fixture={'protected_values':['alpha-hidden-value']}
            headers={'authorization':'Bearer synthetic-only-secret-key'}
            try:
                with self.assertRaises(ValueError):await transport.handle_async_request(httpx.Request('POST','http://127.0.0.1/v1/chat/completions',headers=headers,json=diag.expected_wire_body(transport.expected_messages)))
                with self.assertRaises(ValueError):await transport.handle_async_request(httpx.Request('POST',diag.ENDPOINT,headers=headers,json=diag.expected_wire_body(transport.expected_messages)))
                transport.fixture={}
                changed=diag.expected_wire_body(transport.expected_messages);changed['store']=True
                with self.assertRaises(ValueError):await transport.handle_async_request(httpx.Request('POST',diag.ENDPOINT,headers=headers,json=changed))
                self.assertEqual(ledger.data['attempts'],[])
            finally:ledger.close()

    async def test_failure_has_one_attempt_no_retry_and_keeps_unknown_cost_reserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ledger=diag.BudgetLedger(approved(root/'approval.json'));calls=[]
            def failure(request):
                calls.append(request)
                raise httpx.ReadTimeout('Controlled test failure.',request=request)
            transport=diag.ApprovedTransport(root,ledger,delegate=httpx.MockTransport(failure))
            registry=ProviderRegistry(transport=transport);registry.configure('openai','synthetic-only-secret-key',diag.MODEL)
            try:
                result=await diag.dispatch(registry,transport,'timeout',[{'role':'user','content':'Fictional public test.'}],{})
                self.assertEqual(result['status'],'failed')
                self.assertEqual(len(calls),1)
                self.assertEqual(len(ledger.data['attempts']),1)
                self.assertEqual(ledger.data['attempts'][0]['cost_basis'],'no_valid_usage_full_worst_case_reservation_retained')
                self.assertTrue(transport.records[0]['delivery_unknown'])
            finally:ledger.close()

    async def test_credential_echo_in_response_is_never_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ledger=diag.BudgetLedger(approved(root/'approval.json'));key='synthetic-only-secret-key'
            def echo(request):return httpx.Response(200,headers={'x-request-id':key},json={'error':key})
            transport=diag.ApprovedTransport(root,ledger,delegate=httpx.MockTransport(echo))
            registry=ProviderRegistry(transport=transport);registry.configure('openai',key,diag.MODEL)
            try:
                result=await diag.dispatch(registry,transport,'echo',[{'role':'user','content':'Public fictional text.'}],{})
                self.assertEqual(result['status'],'failed')
                self.assertEqual(transport.records[0]['response_body_omitted'],'credential_echo_not_saved')
                self.assertNotIn('provider_request_id',transport.records[0])
                for path in root.rglob('*'):
                    if path.is_file():self.assertNotIn(key.encode(),path.read_bytes())
            finally:ledger.close()


class SourceSelectionTests(unittest.TestCase):
    def test_incomplete_main_is_rejected_before_selection_or_secret_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);execution=root/'execution';(execution/'runs').mkdir(parents=True)
            (root/'synthetic-inputs.jsonl').write_text(json.dumps({'case_id':'T01-2'})+'\n')
            diag.write_json(execution/'runs/T01-2-B.json',{'status':'failed'})
            with self.assertRaises(ValueError):diag.require_complete_main(root,execution)
            for arm in ['A','C']:diag.write_json(execution/f'runs/T01-2-{arm}.json',{'status':'completed'})
            diag.require_complete_main(root,execution)

    def test_failed_source_answer_with_valid_transformation_is_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);execution=root/'execution';(execution/'runs').mkdir(parents=True)
            case={'case_id':'T01-2','task_id':'T01','profile':'approved_external','policy_id':'standard','messages':[{'role':'user','content':'Fictional public fact count 3.'}]}
            fixture={'case_id':'T01-2','protected_values':[],'protected_code_fragments':[],'quality':{'type':'json_fields','expected':{'count':3}}}
            policy=default_policy()
            diag.write_json(root/'policies.json',{'standard':policy})
            diag.write_json(root/'researcher-fixtures.json',[fixture])
            (root/'synthetic-inputs.jsonl').write_text(json.dumps(case)+'\n')
            names=['policies.json','researcher-fixtures.json','synthetic-inputs.jsonl']
            diag.write_json(root/'sample-freeze.json',{'sample_files_sha256':{name:diag.digest((root/name).read_bytes()) for name in names}})
            messages=[{'role':'system','content':'Answer the fictional task.'},*case['messages']]
            body=json.dumps({'model':'local-test-model','messages':messages,'stream':False}).encode()
            (execution/'sent.bin').write_bytes(body);(execution/'received.bin').write_bytes(body)
            record={'run_id':'T01-2-B','case_id':'T01-2','arm':'B','status':'failed','messages_sha256':diag.digest(canonical(case['messages'])),'policy_sha256':diag.digest(canonical(policy)),'events':[{'stage':'decision','decision':{'route':'delegate_sanitized_to_external_ai'}},{'stage':'transformation','status':'completed','payload':messages}],'wire_requests':[{'body_path':'sent.bin','sha256':diag.digest(body),'bytes':len(body)}],'receipts':[{'body_path':'received.bin','sha256':diag.digest(body),'bytes':len(body)}]}
            diag.write_json(execution/'runs/T01-2-B.json',record)
            accepted,excluded=diag.selected_candidates(root,execution)
            self.assertEqual(len(accepted),1)
            self.assertEqual(accepted[0]['source_status'],'failed')
            self.assertEqual(excluded,[])
            changed=body+b' '
            (execution/'received.bin').write_bytes(changed)
            accepted,excluded=diag.selected_candidates(root,execution)
            self.assertEqual(accepted,[])
            self.assertEqual(excluded[0]['reason'],'source_http_bytes_or_hash_mismatch')


if __name__=='__main__':
    unittest.main()
