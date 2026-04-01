import csv
import json
import re
from pathlib import Path
from typing import Any, Optional, Union


def _as_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _get_value_by_keys(row: dict[str, Any], keys: list[str]) -> Optional[Any]:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _normalize_lat_lon(lat: Optional[float], lon: Optional[float]) -> Optional[list[float]]:
    if lat is None or lon is None:
        return None

    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return [lat, lon]

    scaled_lat = lat / 1000000
    scaled_lon = lon / 1000000
    if -90 <= scaled_lat <= 90 and -180 <= scaled_lon <= 180:
        return [scaled_lat, scaled_lon]

    return None


def _parse_linestring_wkt(wkt: str) -> list[list[float]]:
    if not isinstance(wkt, str):
        return []

    match = re.search(r"LINESTRING\s*\((.*)\)", wkt, flags=re.IGNORECASE)
    if not match:
        return []

    points: list[list[float]] = []
    for raw_pair in match.group(1).split(","):
        parts = raw_pair.strip().split()
        if len(parts) < 2:
            continue
        lon = _as_float(parts[0])
        lat = _as_float(parts[1])
        normalized = _normalize_lat_lon(lat, lon)
        if normalized is None:
            continue
        points.append([normalized[1], normalized[0]])
    return points


def _detect_coordinate_mode(points: list[list[float]]) -> str:
    if not points:
        return "geo"

    geo_like = 0
    tiny_like = 0
    for lat, lon in points:
        if abs(lat) > 1 or abs(lon) > 1:
            geo_like += 1
        if abs(lat) < 0.01 and abs(lon) < 0.01:
            tiny_like += 1

    if tiny_like >= max(8, int(len(points) * 0.4)) and geo_like == 0:
        return "image"
    return "geo"


def _read_csv_rows(csv_path: Union[str, Path]) -> list[dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def write_network_geojson(
    output_path: Union[str, Path],
    nodes_csv_path: Optional[Union[str, Path]] = None,
    links_csv_path: Optional[Union[str, Path]] = None,
) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    node_rows = _read_csv_rows(nodes_csv_path) if nodes_csv_path and Path(nodes_csv_path).exists() else []
    link_rows = _read_csv_rows(links_csv_path) if links_csv_path and Path(links_csv_path).exists() else []

    node_lookup: dict[str, list[float]] = {}
    sample_points: list[list[float]] = []
    features: list[dict[str, Any]] = []

    for row in node_rows:
        node_id = _get_value_by_keys(row, ["node_id", "Node_ID", "ID", "id"])
        lat = _as_float(_get_value_by_keys(row, ["Latitude", "latitude", "lat", "y_coord", "Y", "y"]))
        lon = _as_float(_get_value_by_keys(row, ["Longitude", "longitude", "lon", "lng", "x_coord", "X", "x"]))
        normalized = _normalize_lat_lon(lat, lon)
        if normalized is None:
            continue

        sample_points.append(normalized)
        if node_id is not None:
            node_lookup[str(node_id)] = normalized

        properties = dict(row)
        properties["feature_type"] = "node"
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {
                    "type": "Point",
                    "coordinates": [normalized[1], normalized[0]],
                },
            }
        )

    for row in link_rows:
        geometry = []
        geometry_text = _get_value_by_keys(row, ["geometry", "Geometry"])
        if geometry_text:
            geometry = _parse_linestring_wkt(str(geometry_text))

        if not geometry:
            from_lat = _as_float(_get_value_by_keys(row, ["From_Latitude", "from_lat", "from_latitude"]))
            from_lon = _as_float(_get_value_by_keys(row, ["From_Longitude", "from_lon", "from_longitude"]))
            to_lat = _as_float(_get_value_by_keys(row, ["To_Latitude", "to_lat", "to_latitude"]))
            to_lon = _as_float(_get_value_by_keys(row, ["To_Longitude", "to_lon", "to_longitude"]))
            from_point = _normalize_lat_lon(from_lat, from_lon)
            to_point = _normalize_lat_lon(to_lat, to_lon)
            if from_point and to_point:
                geometry = [
                    [from_point[1], from_point[0]],
                    [to_point[1], to_point[0]],
                ]

        if not geometry:
            from_node = _get_value_by_keys(row, ["from_node_id", "From_Node", "from_node"])
            to_node = _get_value_by_keys(row, ["to_node_id", "To_Node", "to_node"])
            if from_node is not None and to_node is not None:
                from_point = node_lookup.get(str(from_node))
                to_point = node_lookup.get(str(to_node))
                if from_point and to_point:
                    geometry = [
                        [from_point[1], from_point[0]],
                        [to_point[1], to_point[0]],
                    ]

        if len(geometry) < 2:
            continue

        sample_points.extend([[coord[1], coord[0]] for coord in geometry])
        properties = dict(row)
        properties["feature_type"] = "link"
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {
                    "type": "LineString",
                    "coordinates": geometry,
                },
            }
        )

    payload = {
        "type": "FeatureCollection",
        "metadata": {
            "coordinate_mode": _detect_coordinate_mode(sample_points),
            "source_files": {
                "nodes": str(nodes_csv_path) if nodes_csv_path else None,
                "links": str(links_csv_path) if links_csv_path else None,
            },
        },
        "features": features,
    }

    with open(output_path, "w", encoding="utf-8") as geojson_file:
        json.dump(payload, geojson_file, ensure_ascii=False, indent=2)

    return str(output_path)