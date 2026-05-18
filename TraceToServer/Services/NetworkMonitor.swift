import Foundation
import Observation

@MainActor
@Observable
class NetworkMonitor {
    var connections: [Connection] = []

    private var timer: Timer?

    func start() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    private func refresh() {
        Task.detached {
            let result = Self.fetchConnections()
            await MainActor.run { self.connections = result }
        }
    }

    // MARK: - lsof parsing

    private static func fetchConnections() -> [Connection] {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        // -F field output: p=PID, c=command, n=name
        process.arguments = ["-i", "TCP", "-n", "-P", "-F", "pcn"]

        let outPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = Pipe()

        do { try process.run() } catch { return [] }
        process.waitUntilExit()

        let data = outPipe.fileHandleForReading.readDataToEndOfFile()
        guard let output = String(data: data, encoding: .utf8) else { return [] }
        return parseOutput(output)
    }

    private static func parseOutput(_ output: String) -> [Connection] {
        var result: [Connection] = []
        var seen = Set<Connection>()
        var pid = 0
        var cmd = ""

        for line in output.components(separatedBy: "\n") {
            guard line.count > 1 else { continue }
            let tag = line.prefix(1)
            let val = String(line.dropFirst())

            switch tag {
            case "p": pid = Int(val) ?? 0
            case "c": cmd = val
            case "n":
                if let conn = parseNetworkLine(val, pid: pid, command: cmd),
                   !seen.contains(conn) {
                    seen.insert(conn)
                    result.append(conn)
                }
            default: break
            }
        }
        return result
    }

    private static func parseNetworkLine(_ line: String, pid: Int, command: String) -> Connection? {
        guard line.contains("->") else { return nil }
        let parts = line.components(separatedBy: "->")
        guard parts.count == 2,
              let local = parseAddress(parts[0]),
              let remote = parseAddress(parts[1]),
              !remote.ip.isEmpty,
              remote.ip != "*",
              !isPrivate(ip: remote.ip) else { return nil }

        return Connection(
            processName: command,
            pid: pid,
            localIP: local.ip,
            localPort: local.port,
            remoteIP: remote.ip,
            remotePort: remote.port
        )
    }

    private static func parseAddress(_ addr: String) -> (ip: String, port: Int)? {
        if addr.hasPrefix("[") {
            // IPv6: [::1]:port
            guard let bracket = addr.lastIndex(of: "]") else { return nil }
            let afterBracket = addr.index(after: bracket)
            guard afterBracket < addr.endIndex, addr[afterBracket] == ":" else { return nil }
            let ip = String(addr[addr.index(after: addr.startIndex)..<bracket])
            let port = Int(addr[addr.index(after: afterBracket)...]) ?? 0
            return (ip, port)
        } else {
            let parts = addr.components(separatedBy: ":")
            guard parts.count >= 2 else { return nil }
            let port = Int(parts.last ?? "") ?? 0
            let ip = parts.dropLast().joined(separator: ":")
            return (ip, port)
        }
    }

    private static func isPrivate(ip: String) -> Bool {
        let prefixes = ["10.", "127.", "::1", "fe80", "fc", "fd"]
        if prefixes.contains(where: { ip.hasPrefix($0) }) { return true }
        if ip == "localhost" { return true }
        if ip.hasPrefix("192.168.") { return true }
        if ip.hasPrefix("172.") {
            let parts = ip.components(separatedBy: ".")
            if let second = Int(parts[safe: 1] ?? ""), (16...31).contains(second) { return true }
        }
        return false
    }
}

private extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
