import AppKit
import Foundation
import Darwin

if CommandLine.arguments.dropFirst().first == "--self-test" {
    print("aethon-key-entry ready")
    exit(0)
}

let arguments = Array(CommandLine.arguments.dropFirst())
let labels = ["openai": "OpenAI", "anthropic": "Anthropic", "remote": "your remote endpoint"]
guard let provider = arguments.first, let label = labels[provider] else { exit(2) }
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
let guardian = DispatchSource.makeTimerSource(queue: .global())
if arguments.count >= 3, let parent = Int32(arguments[2]) {
    guardian.schedule(deadline: .now() + 1, repeating: 1)
    guardian.setEventHandler { if getppid() != parent { exit(2) } }
    guardian.resume()
}
let alert = NSAlert()
alert.messageText = "Connect \(label) to aethon"
alert.informativeText = "Enter your API key. It stays in the local service's memory for this session. aethon does not save it. Quit aethon to clear the connection."
alert.alertStyle = .informational
alert.addButton(withTitle: "Connect")
alert.addButton(withTitle: "Cancel")
let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 370, height: 26))
field.placeholderString = "API key"
field.isEditable = true
field.isSelectable = true
alert.accessoryView = field
if arguments.count >= 2 { alert.icon = NSImage(contentsOfFile: arguments[1]) }
alert.window.initialFirstResponder = field
application.activate(ignoringOtherApps: true)
guard alert.runModal() == .alertFirstButtonReturn else { exit(2) }
let key = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
guard !key.isEmpty, key.utf8.count <= 1024, !key.contains("\0") else { exit(3) }
FileHandle.standardOutput.write(Data(key.utf8))
