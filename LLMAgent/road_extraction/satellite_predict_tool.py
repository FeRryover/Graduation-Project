from LLMAgent.road_extraction import satellite_predict


def prompts(name, description):
    def decorator(func):
        func.name = name
        func.description = description
        return func
    return decorator


class satellite_pic_road_extraction:
    def __init__(self, imgfile: str) -> None:
        self.imgfile = imgfile

    @prompts(name='Extract Road from Satellite Image',
             description="""
             Recognize a satellite road map image and provide a compressed GMNS file with road node details, along with a visual representation of the recognized road network.
             The input should be a path to the satellite image which needs to be processed.
             The output is a path to the generated zip file containing gmns-style files, and a path to the visual representation of the recognized road network.
             """)

    def inference(self, imgfile: str) -> str:
        GMNS_path, best_img_name = satellite_predict.predict_road_from_satellite_image(imgfile)
        return f'The path to the generated zipped gmns file is: `{GMNS_path}`. The path to the visual representation of the recognized road network is: `{best_img_name}`. Process finished.'
