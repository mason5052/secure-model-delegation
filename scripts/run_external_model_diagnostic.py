"""Run an explicitly approved, bounded diagnostic on frozen synthetic representations."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from decimal import Decimal
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / 'src'))

import httpx

from smd_app.agent_gateway import provider_agent_complete
from smd_app.engine import validate_policy
from smd_app.evaluation import canonical, disclosure_check, quality_check
from smd_app.providers import ProviderError, ProviderRegistry

MODEL = 'gpt-5.4-mini-2026-03-17'
ENDPOINT = 'https://api.openai.com/v1/chat/completions'
MAX_ATTEMPTS = 25
MAX_COST = Decimal('1.00')
MAX_BODY_BYTES = 4800
INPUT_TOKEN_RESERVE = 6000
MAX_OUTPUT_TOKENS = 2048
INPUT_RATE = Decimal('0.75')
OUTPUT_RATE = Decimal('4.50')
SCOPE = 'frozen_synthetic_transformed_messages_only'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n')
    os.replace(temporary, path)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def below(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('An evidence path is missing or outside its execution directory.')
    return path


@dataclass(frozen=True)
class Approval:
    path: Path
    sha256: str
    max_attempts: int
    max_cost: Decimal
    reference: str

    @classmethod
    def read(cls, path: Path) -> 'Approval':
        raw = path.read_bytes()
        value = json.loads(raw)
        if value.get('approved') is not True or value.get('provider') != 'openai' or value.get('model') != MODEL:
            raise ValueError('Explicit approval for this provider and pinned model is required.')
        if value.get('endpoint') != ENDPOINT or value.get('data_scope') != SCOPE:
            raise ValueError('The approved endpoint or synthetic-data scope does not match.')
        attempts = value.get('max_attempts')
        if type(attempts) is not int or not 1 <= attempts <= MAX_ATTEMPTS:
            raise ValueError('The approved attempt cap is outside the supported bound.')
        cost = Decimal(str(value.get('max_cost_usd', '0')))
        if not cost.is_finite() or not Decimal('0') < cost <= MAX_COST:
            raise ValueError('The approved cost cap is outside the supported bound.')
        rates = value.get('pricing_usd_per_million', {})
        if Decimal(str(rates.get('input', '-1'))) != INPUT_RATE or Decimal(str(rates.get('output', '-1'))) != OUTPUT_RATE:
            raise ValueError('The pricing approval does not match the frozen conservative rates.')
        reference = value.get('approval_reference')
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError('A non-secret approval reference is required.')
        return cls(path.resolve(), digest(raw), attempts, cost, reference)


def request_body(messages: list[dict]) -> dict:
    return {'model': 'smd-openai', 'messages': messages, 'temperature': 0,
            'reasoning_effort': 'none', 'max_completion_tokens': MAX_OUTPUT_TOKENS}


def expected_wire_body(messages: list[dict]) -> dict:
    body = {key: value for key, value in request_body(messages).items() if key != 'model'}
    body.update(model=MODEL, stream=False, store=False)
    return body


def preview_bytes(messages: list[dict]) -> bytes:
    return httpx.Request('POST', ENDPOINT, json=expected_wire_body(messages)).content


def has_fixture_finding(check: dict) -> bool:
    return any(check.get(key) for key in ('direct_protected_values', 'normalized_or_decoded_values', 'protected_code_fragments'))


def require_complete_main(frozen_run: Path, execution: Path) -> None:
    cases = [json.loads(line) for line in (frozen_run / 'synthetic-inputs.jsonl').read_text().splitlines()]
    expected = {case['case_id'] + '-' + arm for case in cases for arm in ('A', 'B', 'C')}
    actual = {path.stem for path in (execution / 'runs').glob('*.json')}
    if actual != expected:
        raise ValueError('The frozen main comparison must have every planned outcome, including failures, before diagnostic selection.')


def selected_candidates(frozen_run: Path, execution: Path) -> tuple[list[dict], list[dict]]:
    freeze = json.loads((frozen_run / 'sample-freeze.json').read_text())
    for name, expected in freeze['sample_files_sha256'].items():
        if digest(below(frozen_run, name).read_bytes()) != expected:
            raise ValueError('A frozen sample file has changed.')
    cases = {row['case_id']: row for row in (json.loads(line) for line in (frozen_run / 'synthetic-inputs.jsonl').read_text().splitlines())}
    fixtures = {row['case_id']: row for row in json.loads((frozen_run / 'researcher-fixtures.json').read_text())}
    policies = json.loads((frozen_run / 'policies.json').read_text())
    for policy in policies.values():
        validate_policy(policy)
    accepted, excluded = [], []
    for path in sorted((execution / 'runs').glob('*.json')):
        record = json.loads(path.read_text())
        identity = {'run_id': record.get('run_id', path.stem), 'case_id': record.get('case_id'), 'source_status': record.get('status')}
        case = cases.get(record.get('case_id'))
        if case is None or case['profile'] != 'approved_external':
            excluded.append({**identity, 'reason': 'not_an_approved_external_condition'})
            continue
        try:
            policy = policies[case['policy_id']]
            if record['messages_sha256'] != digest(canonical(case['messages'])) or record['policy_sha256'] != digest(canonical(policy)):
                raise ValueError('frozen_input_or_policy_hash_mismatch')
            decisions = [event['decision'] for event in record.get('events', []) if event.get('stage') == 'decision' and 'decision' in event]
            selected = record.get('result', {}).get('route') or (decisions[-1].get('route') if decisions else None)
            if selected != 'delegate_sanitized_to_external_ai':
                raise ValueError('no_policy_selected_external_route')
            transformations = [event['payload'] for event in record.get('events', []) if event.get('stage') == 'transformation' and event.get('status') == 'completed' and 'payload' in event]
            if len(transformations) != 1:
                raise ValueError('no_unique_completed_transformation')
            messages = transformations[0]
            ProviderRegistry._validate_messages(messages)
            result_payload = record.get('result', {}).get('payload')
            if result_payload is not None and result_payload != messages:
                raise ValueError('result_transformation_mismatch')
            wires, receipts = record.get('wire_requests', []), record.get('receipts', [])
            if len(wires) != 1 or len(receipts) != 1:
                raise ValueError('no_unique_actual_source_http_receipt')
            sent = below(execution, wires[0]['body_path']).read_bytes()
            received = below(execution, receipts[0]['body_path']).read_bytes()
            if sent != received or digest(sent) != wires[0]['sha256'] or digest(received) != receipts[0]['sha256'] or len(sent) != wires[0]['bytes'] or len(received) != receipts[0]['bytes']:
                raise ValueError('source_http_bytes_or_hash_mismatch')
            if json.loads(received).get('messages') != messages:
                raise ValueError('source_received_messages_differ_from_transformation')
            check = disclosure_check(preview_bytes(messages).decode(), fixtures[case['case_id']])
            if has_fixture_finding(check):
                raise ValueError('protected_fixture_residual')
            if len(preview_bytes(messages)) > MAX_BODY_BYTES:
                raise ValueError('serialized_request_exceeds_frozen_byte_cap')
            accepted.append({**identity, 'source_record_sha256': digest(path.read_bytes()), 'source_record_path': str(path), 'task_id': case['task_id'], 'arm': record.get('arm'), 'messages': messages, 'messages_sha256': digest(canonical(messages)), 'source_http_sha256': digest(received), 'preview_request_sha256': digest(preview_bytes(messages)), 'preview_request_bytes': len(preview_bytes(messages)), 'fixture': fixtures[case['case_id']], 'source_answer_success_was_not_a_selection_criterion': True})
        except (KeyError, TypeError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) and re.fullmatch('[a-z_]+', str(exc)) else 'invalid_or_incomplete_source_evidence'
            excluded.append({**identity, 'reason': reason})
    return accepted, excluded


class BudgetLedger:
    def __init__(self, approval: Approval):
        self.approval = approval
        self.path = approval.path.with_name(approval.path.name + '.attempt-ledger.json')
        self.lock = approval.path.with_name(approval.path.name + '.attempt-ledger.lock')
        descriptor = os.open(self.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        try:
            self.data = json.loads(self.path.read_text()) if self.path.exists() else {'approval_sha256': approval.sha256, 'attempts': []}
            if self.data['approval_sha256'] != approval.sha256:
                raise ValueError('The existing spend ledger belongs to a different approval.')
            for row in self.data['attempts']:
                cost = Decimal(row['committed_cost_upper_bound_usd'])
                if not cost.is_finite() or cost < 0:
                    raise ValueError('The spend ledger contains an invalid reservation.')
        except BaseException:
            self.close()
            raise

    def close(self):
        self.lock.unlink(missing_ok=True)

    @property
    def total(self):
        return sum((Decimal(row['committed_cost_upper_bound_usd']) for row in self.data['attempts']), Decimal('0'))

    def reserve(self, label: str) -> dict:
        reserve = (INPUT_RATE * INPUT_TOKEN_RESERVE + OUTPUT_RATE * MAX_OUTPUT_TOKENS) / Decimal(1000000)
        if len(self.data['attempts']) >= self.approval.max_attempts or self.total + reserve > self.approval.max_cost:
            raise ValueError('The approved attempt or conservative spend cap is exhausted.')
        row = {'attempt': len(self.data['attempts']) + 1, 'label': label, 'reserved_at_utc': now(), 'status': 'reserved_before_dispatch', 'committed_cost_upper_bound_usd': str(reserve), 'reserved_input_tokens': INPUT_TOKEN_RESERVE, 'reserved_output_tokens': MAX_OUTPUT_TOKENS}
        self.data['attempts'].append(row)
        write_json(self.path, self.data)
        return row

    def finish(self, row: dict, status: str, usage: dict | None):
        row['status'] = status
        if isinstance(usage, dict) and all(type(usage.get(name)) is int and usage[name] >= 0 for name in ('prompt_tokens', 'completion_tokens')):
            cost = (INPUT_RATE * usage['prompt_tokens'] + OUTPUT_RATE * usage['completion_tokens']) / Decimal(1000000)
            row['committed_cost_upper_bound_usd'] = str(cost)
            row['usage'] = usage
            row['cost_basis'] = 'reported_usage_at_uncached_rates_not_an_invoice'
            row['usage_exceeded_reserved_token_bound'] = usage['prompt_tokens'] > INPUT_TOKEN_RESERVE or usage['completion_tokens'] > MAX_OUTPUT_TOKENS
        else:
            row['cost_basis'] = 'no_valid_usage_full_worst_case_reservation_retained'
        write_json(self.path, self.data)


class ApprovedTransport(httpx.AsyncBaseTransport):
    def __init__(self, output: Path, ledger: BudgetLedger, *, delegate=None):
        self.output, self.ledger = output, ledger
        self.delegate = delegate
        self.label = 'unset'
        self.expected_messages = None
        self.fixture = {}
        self.records = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != 'POST' or str(request.url) != ENDPOINT:
            raise ValueError('Only the approved official HTTPS endpoint may be called.')
        raw = await request.aread()
        data = json.loads(raw)
        if self.expected_messages is None or data != expected_wire_body(self.expected_messages) or len(raw) > MAX_BODY_BYTES:
            raise ValueError('The serialized request differs from the approved frozen settings or size.')
        if has_fixture_finding(disclosure_check(raw.decode(), self.fixture)):
            raise ValueError('A protected synthetic fixture remains; no request was dispatched.')
        authorization = request.headers.get('authorization', '')
        if not authorization.startswith('Bearer ') or len(authorization) < 16:
            raise ValueError('The in-memory provider credential is unavailable.')
        secret = authorization[len('Bearer '):].encode()
        if secret and secret in raw:
            raise ValueError('Credential-shaped content cannot be saved or dispatched.')
        reservation = self.ledger.reserve(self.label)
        number = reservation['attempt']
        name = f'attempt-{number:03d}'
        request_path = self.output / 'requests' / (name + '.bin')
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_bytes(raw)
        record = {'attempt': number, 'label': self.label, 'started_at_utc': now(), 'endpoint': ENDPOINT, 'request_body_path': str(request_path.relative_to(self.output)), 'request_sha256': digest(raw), 'request_bytes': len(raw), 'request_headers_saved': False, 'response_headers_saved': ['x-request-id_only_when_present']}
        self.records.append(record)
        started = time.perf_counter()
        usage = None
        try:
            transport = self.delegate or httpx.AsyncHTTPTransport(retries=0)
            try:
                response = await transport.handle_async_request(request)
                await response.aread()
            finally:
                if self.delegate is None:
                    await transport.aclose()
            record['http_status'] = response.status_code
            response_raw = response.content
            record['response_sha256'] = digest(response_raw)
            record['response_bytes'] = len(response_raw)
            request_id = response.headers.get('x-request-id')
            if request_id and secret not in request_id.encode() and re.fullmatch('[A-Za-z0-9_-]{1,200}', request_id):
                record['provider_request_id'] = request_id
            if secret and secret in response_raw:
                record['response_body_omitted'] = 'credential_echo_not_saved'
                raise ValueError('A response echoed the credential; its body was not saved.')
            response_path = self.output / 'responses' / (name + '.json')
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_bytes(response_raw)
            record['response_body_path'] = str(response_path.relative_to(self.output))
            try:
                parsed = json.loads(response_raw)
                usage = parsed.get('usage') if isinstance(parsed, dict) else None
            except ValueError:
                pass
            record['status'] = 'response_received'
            return response
        except BaseException as exc:
            record['status'] = 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'transport_or_validation_failed'
            record['error_type'] = type(exc).__name__
            record['delivery_unknown'] = isinstance(exc, (httpx.RequestError, asyncio.CancelledError))
            raise
        finally:
            record['seconds'] = time.perf_counter() - started
            record['usage'] = usage
            self.ledger.finish(reservation, record.get('status', 'failed'), usage)
            write_json(self.output / 'attempts' / (name + '.json'), record)

    async def aclose(self):
        pass


async def dispatch(registry: ProviderRegistry, transport: ApprovedTransport, label: str, messages: list[dict], fixture: dict) -> dict:
    transport.label, transport.expected_messages, transport.fixture = label, messages, fixture
    before = len(transport.records)
    result = {'label': label, 'status': 'not_dispatched', 'quality': {'status': 'not_evaluated', 'success': None}}
    try:
        reply, actual = await provider_agent_complete(registry, 'openai', request_body(messages))
        if actual != expected_wire_body(messages):
            raise ValueError('The provider adapter changed its serialized request contract.')
        choice = reply['choices'][0]
        message = choice['message']
        answer = message.get('content') or ''
        result.update(status='response_received', answer=answer, finish_reason=choice.get('finish_reason'), provider_response_id=reply.get('id'), quality=quality_check(answer, fixture))
        if choice.get('finish_reason') != 'stop':
            result['quality'] = {'status':'incomplete_generation', 'success':False}
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        result.update(status='cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed', error_type=type(exc).__name__, error_code=getattr(exc, 'code', None), delivery_unknown=bool(getattr(exc, 'delivery_unknown', False)), quality={'status':'execution_failure','success':False})
    result['attempt_records'] = transport.records[before:]
    return result


async def run(args):
    approval = Approval.read(args.approval)
    require_complete_main(args.frozen_run, args.execution)
    accepted, excluded = selected_candidates(args.frozen_run, args.execution)
    args.output.mkdir(parents=True, exist_ok=False)
    public_selection = [{key:value for key,value in candidate.items() if key not in {'messages','fixture'}} for candidate in accepted]
    write_json(args.output / 'candidate-selection.json', {'accepted':public_selection,'selection_excludes_source_answer_quality':True,'source_failures_with_valid_transformation_are_eligible':True})
    with (args.output / 'excluded-candidates.csv').open('w',newline='') as handle:
        fields=['run_id','case_id','source_status','reason'];writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(excluded)
    manifest = {'scope':'secondary_frozen_representation_diagnostic_not_a_new_full_A_B_C_routing_experiment','approval_sha256':approval.sha256,'approval_reference':approval.reference,'model':MODEL,'endpoint':ENDPOINT,'max_attempts':approval.max_attempts,'max_cost_usd':str(approval.max_cost),'input_rate_usd_per_million':str(INPUT_RATE),'output_rate_usd_per_million':str(OUTPUT_RATE),'cost_reporting':'reported_usage_at_uncached_rates_is_an_upper_bound_not_billing_evidence','input_token_reserve':INPUT_TOKEN_RESERVE,'max_serialized_request_bytes':MAX_BODY_BYTES,'max_completion_tokens':MAX_OUTPUT_TOKENS,'temperature':0,'reasoning_effort':'none','store':False,'stream':False,'retry_count':0,'timeout_seconds':120,'compatibility_probe_counts_toward_cap':True,'script_sha256':digest(Path(__file__).read_bytes()),'adapter_hashes':{name:digest((APP_ROOT/'src/smd_app'/name).read_bytes()) for name in ['providers.py','agent_gateway.py','evaluation.py']},'frozen_sample_manifest_sha256':digest((args.frozen_run/'sample-freeze.json').read_bytes()),'prepared_at_utc':now(),'status':'PREPARED_NO_DISPATCH' if not args.execute else 'EXECUTION_REQUESTED'}
    write_json(args.output/'manifest.json',manifest)
    if not args.execute:
        print(json.dumps({'status':'prepared_no_dispatch','safe_candidates':len(accepted),'excluded':len(excluded),'calls':0,'output':str(args.output)}))
        return
    secret = sys.stdin.readline(4097).strip()
    if not secret or len(secret)>512 or any(character.isspace() for character in secret):
        raise ValueError('A valid in-memory secret is required on standard input; no credential was saved.')
    ledger = BudgetLedger(approval)
    records=[]
    try:
        transport=ApprovedTransport(args.output,ledger)
        registry=ProviderRegistry(transport=transport,timeout=120)
        registry.configure('openai',secret,MODEL)
        probe_messages=[{'role':'system','content':'Use only this fictional public test. Return the requested JSON.'},{'role':'user','content':'Return only JSON with field status set to ready.'}]
        probe_fixture={'quality':{'type':'json_fields','expected':{'status':'ready'}}}
        probe=await dispatch(registry,transport,'compatibility-probe',probe_messages,probe_fixture)
        records.append(probe)
        write_json(args.output/'compatibility-probe.json',probe)
        if probe['status']=='response_received' and probe['quality'].get('success'):
            for candidate in accepted:
                if len(ledger.data['attempts'])>=approval.max_attempts:
                    break
                row=await dispatch(registry,transport,candidate['run_id'],candidate['messages'],candidate['fixture'])
                row.update(case_id=candidate['case_id'],task_id=candidate['task_id'],source_arm=candidate['arm'],source_status=candidate['source_status'],source_record_sha256=candidate['source_record_sha256'],source_http_sha256=candidate['source_http_sha256'])
                records.append(row)
                write_json(args.output/'case-results'/f'{candidate["run_id"]}.json',row)
                if row['status']!='response_received' or ledger.total>approval.max_cost or any(x.get('usage_exceeded_reserved_token_bound') for x in ledger.data['attempts']):
                    break
        write_json(args.output/'summary.json',{'status':'COMPLETED_OR_STOPPED_WITHOUT_RETRY','actual_attempts_this_run':len(transport.records),'total_approved_attempts_in_ledger':len(ledger.data['attempts']),'committed_cost_upper_bound_usd':str(ledger.total),'main_candidate_calls':max(0,len(transport.records)-1),'main_candidate_field_successes':sum(row['quality'].get('success') is True for row in records[1:]),'main_candidate_outcomes':len(records)-1,'source_full_comparison_reexecuted':False,'C_forced_to_delegate':False,'independent_human_review_completed':False,'provider_receipt_independently_observed':False,'retention_or_training_policy_verified':False,'raw_authorization_headers_saved':False})
        print(json.dumps({'status':'finished','attempts':len(transport.records),'cost_upper_bound_usd':str(ledger.total),'output':str(args.output)}))
    finally:
        ledger.close()
        secret=''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval',type=Path,required=True)
    parser.add_argument('--frozen-run',type=Path,required=True)
    parser.add_argument('--execution',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execute',action='store_true',help='Read the credential from stdin and make the explicitly approved bounded calls.')
    args=parser.parse_args()
    try:
        asyncio.run(run(args))
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({'status':'stopped_without_retry','error_type':type(exc).__name__,'message':'Approval, frozen evidence, output state or secret validation failed. No credential is reported.'}),file=sys.stderr)
        raise SystemExit(2) from None


if __name__=='__main__':
    main()
