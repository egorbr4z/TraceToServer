import SwiftUI

struct ContentView: View {
    @State private var monitor = NetworkMonitor()
    @State private var geoService = GeoService()
    @State private var countryService = CountryService()

    @State private var selectedCountry: Country?
    @State private var processFilter: String?

    private var filteredConnections: [Connection] {
        guard let filter = processFilter else { return monitor.connections }
        return monitor.connections.filter { $0.processName == filter }
    }

    private var allProcesses: [String] {
        Array(Set(monitor.connections.map { $0.processName })).sorted()
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            WorldMapView(
                countryService: countryService,
                geoService: geoService,
                connections: filteredConnections,
                selectedCountry: $selectedCountry
            )
            .ignoresSafeArea()

            VStack(spacing: 0) {
                Spacer()
                HUDPanel(
                    connections: filteredConnections,
                    allProcesses: allProcesses,
                    selectedCountry: selectedCountry,
                    geoService: geoService,
                    processFilter: $processFilter,
                    onDismissCountry: { selectedCountry = nil }
                )
            }
        }
        .frame(minWidth: 900, minHeight: 600)
        .onAppear { monitor.start() }
        .onChange(of: monitor.connections) { _, connections in
            let ips = connections.compactMap { $0.remoteIP }.filter { !$0.isEmpty }
            geoService.lookup(ips: ips)
        }
    }
}

#Preview {
    ContentView()
}
