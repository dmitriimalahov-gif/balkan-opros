import Foundation
import AppKit
import Vision

let arguments = CommandLine.arguments
guard arguments.count == 2, let image = NSImage(contentsOfFile: arguments[1]) else {
    FileHandle.standardError.write("Usage: ocr_vision.swift <image>\n".data(using: .utf8)!)
    exit(2)
}
guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("Cannot decode image\n".data(using: .utf8)!)
    exit(3)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
if #available(macOS 13, *) {
    request.revision = VNRecognizeTextRequestRevision3
}
let supported = try VNRecognizeTextRequest.supportedRecognitionLanguages(for: .accurate, revision: request.revision)
let preferred = ["ru-RU", "ro-RO", "en-US", "en-GB"]
let languages = preferred.filter { supported.contains($0) }
if !languages.isEmpty {
    request.recognitionLanguages = languages
}

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
try handler.perform([request])
let lines = (request.results ?? []).compactMap { observation in
    observation.topCandidates(1).first?.string
}
print(lines.joined(separator: "\n"))
