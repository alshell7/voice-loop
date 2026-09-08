// Compile on macOS with: swiftc -O macos-audio.swift -o voiceloop-audio-setup
// Public, persistent aliases over two independent, unmodified signed BlackHole drivers.
import Foundation
import CoreAudio

func check(_ status: OSStatus, _ action: String) throws {
    if status != noErr { throw NSError(domain: "VoiceLoop", code: Int(status),
        userInfo: [NSLocalizedDescriptionKey: "\(action) failed (Core Audio \(status))."]) }
}
func property(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) throws -> String {
    var address = AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
                                            mElement: kAudioObjectPropertyElementMain)
    var value: CFString = "" as CFString
    var size = UInt32(MemoryLayout<CFString>.size)
    try check(AudioObjectGetPropertyData(object, &address, 0, nil, &size, &value), "Read device")
    return value as String
}
func devices() throws -> [(AudioDeviceID, String, String)] {
    var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
        mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    try check(AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size), "List devices")
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    try check(AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &ids), "List devices")
    return try ids.map { ($0, try property($0, kAudioDevicePropertyDeviceUID), try property($0, kAudioObjectPropertyName)) }
}
do {
    let existing = try devices()
    let mappings = [("BlackHole 2ch", "VoiceLoop Mic", "org.voiceloop.mic"),
                    ("BlackHole 16ch", "VoiceLoop Speaker", "org.voiceloop.speaker")]
    // Validate both underlying paths before creating either alias.
    for (source, _, _) in mappings {
        guard existing.contains(where: { $0.2 == source }) else {
            throw NSError(domain: "VoiceLoop", code: 2, userInfo: [NSLocalizedDescriptionKey:
                "\(source) is unavailable. Install BlackHole and restart macOS."])
        }
    }
    for (source, name, uid) in mappings {
        if let alias = existing.first(where: { $0.1 == uid }) {
            guard alias.2 == name else { throw NSError(domain: "VoiceLoop", code: 3,
                userInfo: [NSLocalizedDescriptionKey: "Rename the VoiceLoop aggregate to \(name) in Audio MIDI Setup."]) }
            continue
        }
        let base = existing.first(where: { $0.2 == source })!
        let description: [String: Any] = [kAudioAggregateDeviceNameKey: name,
            kAudioAggregateDeviceUIDKey: uid, kAudioAggregateDeviceIsPrivateKey: false,
            kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: base.1]],
            kAudioAggregateDeviceMasterSubDeviceKey: base.1]
        var id: AudioDeviceID = 0
        try check(AudioHardwareCreateAggregateDevice(description as CFDictionary, &id), "Create \(name)")
        guard try property(id, kAudioObjectPropertyName) == name else {
            throw NSError(domain: "VoiceLoop", code: 4, userInfo: [NSLocalizedDescriptionKey: "Could not verify \(name)."])
        }
    }
    print("VoiceLoop Mic and VoiceLoop Speaker are ready. Refresh your meeting app's devices.")
} catch {
    FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8))
    exit(1)
}
