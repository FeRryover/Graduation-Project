import pandas as pd
import osm2gmns as og
import requests
import urllib
from urllib import parse
from urllib import request
import json
from xpinyin import Pinyin
import osmnx as ox
from LLMAgent.OSM.getosmTools import RoadNetworkGenerator

def prompts(name, description):
    def decorator(func):
        func.name = name
        func.description = description
        return func

    return decorator


class vehiclesCounter:
    def __init__(self, csvFile: str) -> None:
        self.csvFile = csvFile

    @prompts(name='Vehicle Number Counter',
             description="""
             Calculate the number of vehicles from start hour to end hour. 
             The input should be a comma seperated string, representing the start hour and the end hour, which should be integers between 0 and 24. 
             The output is the vehicle numbers during this time preiod.
             """)
    def inference(self, inputs: str) -> str:
        start, end = inputs.replace(' ', '').split(',')
        a, b = int(start), int(end)
        df = pd.read_csv(self.csvFile)
        df['time'] = pd.to_datetime(df['time'], format='%H:%M:%S')
        df['hour'] = pd.to_datetime(df['time'], format='%H:%M:%S').dt.hour
        data = df[(df["hour"] >= a) & (df["hour"] < b)]

        return len(data['carid'].unique())


class Evaluation:
    def __init__(self) -> None:
        pass

    @prompts(name="Evaluation",
             description="""
             Evaluation of traffic operation status of a intersection based on vehicle numbers. 
             The input should be a string of a single number, representing the vehicle numbers.
             For example: "40"
             """)
    def inference(self, flow: str) -> str:
        flow = eval(flow)
        if flow < 70:
            return "Normal Operation Status"
        else:
            return "Heavy Traffic Status"
        
        
class generatearoadnetworkmap:
    def __init__(self) -> None:
        pass

    @prompts(name="Generate Road Network Map",
             description="""
                Generate a random road network map based on the place name and search radius (the default search radius is 1000m)
                The input should be a comma-separated string, including a place name(translate to Chinese if not) and search radius, for example: "天安门,1000".
                The output should be the path of the CSV file and the path of the image generated for the road network map.
                Don't run this tool twice.
                """)
    def inference(self, input: str) -> str:
        generator = RoadNetworkGenerator()
        result = generator.generate_road_network_map(input)
        return result