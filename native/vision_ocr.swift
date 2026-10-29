import Foundation
import Vision
import ImageIO

do {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    guard let source = CGImageSourceCreateWithData(input as CFData, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw NSError(domain: "FloatTranslateOCR", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid image input"])
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    if CommandLine.arguments.contains("--fast") { request.recognitionLevel = .fast }
    if CommandLine.arguments.contains("--cpu") { request.usesCPUOnly = true }
    if CommandLine.arguments.contains("--revision2") { request.revision = VNRecognizeTextRequestRevision2 }
    request.usesLanguageCorrection = true
    if CommandLine.arguments.count > 1 && !CommandLine.arguments[1].isEmpty {
        request.recognitionLanguages = [CommandLine.arguments[1]]
    } else {
        request.automaticallyDetectsLanguage = true
    }
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try handler.perform([request])
    let lines: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let text = observation.topCandidates(1).first?.string else { return nil }
        let box = observation.boundingBox
        return ["text": text, "x": box.minX, "y": 1 - box.maxY, "width": box.width, "height": box.height]
    }
    let output = try JSONSerialization.data(withJSONObject: ["lines": lines])
    FileHandle.standardOutput.write(output)
} catch {
    FileHandle.standardError.write(Data(error.localizedDescription.utf8))
    exit(1)
}
