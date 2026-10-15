// On-device text recognition with Apple's Vision framework.
// Reads image paths from stdin (one per line), prints one JSON object per image, in input order.
// Boxes are normalized [x, y, width, height] with a top-left origin.
import Foundation
import ImageIO
import Vision

let fast = CommandLine.arguments.contains("--fast")
var paths: [String] = []
while let line = readLine() {
    let p = line.trimmingCharacters(in: .whitespacesAndNewlines)
    if !p.isEmpty { paths.append(p) }
}

var results = [String](repeating: "", count: paths.count)
let lock = NSLock()

DispatchQueue.concurrentPerform(iterations: paths.count) { i in
    let path = paths[i]
    var out: [String: Any] = ["path": path]
    var lines: [[String: Any]] = []
    let url = URL(fileURLWithPath: path) as CFURL
    if let source = CGImageSourceCreateWithURL(url, nil),
       let image = CGImageSourceCreateImageAtIndex(source, 0, nil) {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = fast ? .fast : .accurate
        request.usesLanguageCorrection = true
        do {
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
            for observation in request.results ?? [] {
                guard let top = observation.topCandidates(1).first else { continue }
                let b = observation.boundingBox
                lines.append([
                    "text": top.string,
                    "conf": Double(top.confidence),
                    "box": [Double(b.minX), Double(1 - b.maxY), Double(b.width), Double(b.height)],
                ])
            }
        } catch {
            out["error"] = "\(error)"
        }
    } else {
        out["error"] = "unreadable image"
    }
    out["lines"] = lines
    let data = (try? JSONSerialization.data(withJSONObject: out)) ?? Data("{}".utf8)
    lock.lock()
    results[i] = String(data: data, encoding: .utf8) ?? "{}"
    lock.unlock()
}

for r in results { print(r) }
