import matplotlib.pyplot as plt
def visualize_road_network(nodes, edges, file_path):
    plt.figure(figsize=(20, 20))
    for node_id, node_info in nodes.items():
        plt.plot(node_info['lon'], node_info['lat'], marker='o', markersize=8, color='blue')
    for edge in edges:
        from_lat, from_lon = edge['from_lat'], edge['from_lon']
        to_lat, to_lon = edge['to_lat'], edge['to_lon']
        plt.plot([from_lon, to_lon], [from_lat, to_lat], color='gray')
    plt.title("Road Network")
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.savefig(file_path)
    plt.close()