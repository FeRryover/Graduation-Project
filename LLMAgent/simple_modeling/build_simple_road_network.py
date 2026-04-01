center_lat = 39.125
center_lon = 161.567
scale = 0.004
def build_simple_road_network(n, m, num_lanes=2):
    nodes = {}  # 存储节点信息的字典
    edges = []  # 存储边（道路）信息的列表
    n = eval(n)
    m = eval(m)
    for i in range(n):
        for j in range(m):
            node_id = f"Node_{i}_{j}"
            lat = center_lat + ((i - float(n / 2) + 0.5) * scale)
            lon = center_lon + ((j - float(m / 2) + 0.5) * scale)
            lat = round(lat, 4)
            lon = round(lon, 4)
            nodes[node_id] = {'id': node_id, 'lat': lat, 'lon': lon}
            edge_id_counter = 0

            if j > 0:
                from_node = f"Node_{i}_{j - 1}"
                to_node = node_id
                edge_id_counter += j
                edge_id = edge_id_counter
                edges.append({'from_node': from_node,
                              'to_node': to_node,
                              'from_lat': nodes[from_node]['lat'],
                              'from_lon': nodes[from_node]['lon'],
                              'to_lat': lat,
                              'to_lon': lon,
                              'num_lanes': num_lanes,
                              'geometry': [{'lat': nodes[from_node]['lat'], 'lon': nodes[from_node]['lon']},
                                           {'lat': lat, 'lon': lon}],
                              'edge_id': {edge_id}})
            if i > 0:
                from_node = f"Node_{i - 1}_{j}"
                to_node = node_id
                edge_id_counter += i
                edge_id = edge_id_counter
                edges.append({'from_node': from_node,
                              'to_node': to_node,
                              'from_lat': nodes[from_node]['lat'],
                              'from_lon': nodes[from_node]['lon'],
                              'to_lat': lat,
                              'to_lon': lon,
                              'num_lanes': num_lanes,
                              'geometry': [{'lat': nodes[from_node]['lat'], 'lon': nodes[from_node]['lon']},
                                           {'lat': lat, 'lon': lon}],
                              'edge_id': {edge_id}})

                for idx, edge_id in enumerate(edges, start=1):
                    edge_id['edge_id'] = idx

    return {'nodes': nodes, 'edges': edges}