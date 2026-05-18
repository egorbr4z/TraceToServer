import Foundation

struct Connection: Identifiable, Hashable {
    let id: UUID
    let processName: String
    let pid: Int
    let localIP: String
    let localPort: Int
    let remoteIP: String
    let remotePort: Int

    init(processName: String, pid: Int, localIP: String, localPort: Int, remoteIP: String, remotePort: Int) {
        self.id = UUID()
        self.processName = processName
        self.pid = pid
        self.localIP = localIP
        self.localPort = localPort
        self.remoteIP = remoteIP
        self.remotePort = remotePort
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(processName)
        hasher.combine(remoteIP)
        hasher.combine(remotePort)
    }

    static func == (lhs: Connection, rhs: Connection) -> Bool {
        lhs.processName == rhs.processName &&
        lhs.remoteIP == rhs.remoteIP &&
        lhs.remotePort == rhs.remotePort
    }
}
