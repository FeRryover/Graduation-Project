import csv
def save_nodes_to_csv(nodes, csv_path):
    with open(csv_path, 'w', newline='') as node_csv_file:
        node_csv_writer = csv.writer(node_csv_file)
        node_csv_writer.writerow(['ID', 'Latitude', 'Longitude'])
        for node_id, node_info in nodes.items():
            node_csv_writer.writerow([node_id, node_info['lat'], node_info['lon']])

def save_edges_to_csv(edges, csv_path):
    with open(csv_path, 'w', newline='') as edge_csv_file:
        edge_csv_writer = csv.writer(edge_csv_file)
        edge_csv_writer.writerow(
            ['From_Node', 'To_Node', 'From_Latitude', 'From_Longitude', 'To_Latitude', 'To_Longitude',
             'num_lanes',
             'geometry'])
        for edge in edges:
            edge_csv_writer.writerow(
                [edge['from_node'], edge['to_node'], edge['from_lat'], edge['from_lon'], edge['to_lat'],
                 edge['to_lon'], edge['num_lanes'], edge['geometry']])