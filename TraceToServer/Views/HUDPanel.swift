import SwiftUI

struct HUDPanel: View {
    let connections: [Connection]
    let allProcesses: [String]
    let selectedCountry: Country?
    let geoService: GeoService
    @Binding var processFilter: String?
    let onDismissCountry: () -> Void

    private var connectionsInCountry: [Connection] {
        guard let country = selectedCountry else { return [] }
        return connections.filter { conn in
            geoService.locations[conn.remoteIP]?.countryCode == country.id
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            Divider().opacity(0.3)

            HStack(alignment: .top, spacing: 20) {
                // Left: stats + process filter
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 16) {
                        statBadge(label: "CONNECTIONS", value: "\(connections.count)")
                        statBadge(label: "GEOLOCATED", value: "\(connections.filter { geoService.locations[$0.remoteIP] != nil }.count)")
                    }

                    processFilterView
                }
                .frame(minWidth: 200, alignment: .leading)

                Divider()
                    .frame(height: 60)
                    .opacity(0.3)

                // Center: country detail or hint
                Group {
                    if let country = selectedCountry {
                        countryDetailView(country: country)
                    } else {
                        hintView
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                // Right: own location
                if let own = geoService.ownLocation {
                    Divider().frame(height: 60).opacity(0.3)
                    VStack(alignment: .trailing, spacing: 4) {
                        Text("MY LOCATION")
                            .font(.system(size: 9, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.secondary)
                        Text("\(own.city), \(own.country)")
                            .font(.system(size: 12, weight: .medium, design: .monospaced))
                            .foregroundStyle(.primary)
                        Text(own.ip)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                    .frame(minWidth: 160, alignment: .trailing)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
        }
        .background(.regularMaterial)
    }

    // MARK: - Subviews

    private var processFilterView: some View {
        HStack(spacing: 6) {
            Text("PROCESS")
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(.secondary)

            Menu {
                Button("All processes") { processFilter = nil }
                Divider()
                ForEach(allProcesses, id: \.self) { proc in
                    Button(proc) { processFilter = proc }
                }
            } label: {
                HStack(spacing: 4) {
                    Text(processFilter ?? "all")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.primary)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 5))
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
    }

    private func countryDetailView(_ country: Country) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(country.name.uppercased())
                    .font(.system(size: 13, weight: .bold, design: .monospaced))
                    .foregroundStyle(Color(red: 0.4, green: 0.8, blue: 1.0))

                Text("·  \(connectionsInCountry.count) connection\(connectionsInCountry.count == 1 ? "" : "s")")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.secondary)

                Spacer()

                Button(action: onDismissCountry) {
                    Image(systemName: "xmark")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }

            if connectionsInCountry.isEmpty {
                Text("No active connections")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.tertiary)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(connectionsInCountry) { conn in
                            connectionChip(conn)
                        }
                    }
                }
            }
        }
    }

    private func connectionChip(_ conn: Connection) -> some View {
        let geo = geoService.locations[conn.remoteIP]
        return VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                Circle()
                    .fill(Color.red.opacity(0.8))
                    .frame(width: 5, height: 5)
                Text(conn.processName)
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.primary)
            }
            Text("\(conn.remoteIP):\(conn.remotePort)")
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.secondary)
            if let city = geo?.city {
                Text(city)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 7))
    }

    private var hintView: some View {
        Text("Click a country on the map to inspect connections")
            .font(.system(size: 11, design: .monospaced))
            .foregroundStyle(.tertiary)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func statBadge(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.system(size: 8, weight: .semibold, design: .monospaced))
                .foregroundStyle(.tertiary)
            Text(value)
                .font(.system(size: 18, weight: .bold, design: .monospaced))
                .foregroundStyle(Color(red: 0.4, green: 0.8, blue: 1.0))
        }
    }
}
