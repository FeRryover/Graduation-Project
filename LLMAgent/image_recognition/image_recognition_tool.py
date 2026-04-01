from LLMAgent.image_recognition.image_recognition import recognition

def prompts(name, description):
    def decorator(func):
        func.name = name
        func.description = description
        return func

    return decorator


class image_recognition:
    def __init__(self, file: str) -> None:
        self.file = file

    @prompts(name='Identify Hand Drawn Image',
             description="""
             Recognize a hand-drawn road map image and provide a compressed GMNS file with road node details, a GeoJSON network file, and a visual representation of the recognized road network.
             The input should be a path to the image which needs to be processed.
             The output is a path to the generated zip file containing gmns-style files, a path to the generated GeoJSON file, and a path to the visual representation of the recognized road network.
             """)
    def inference(self, file: str) -> str:
        gmns_path, best_img_name, geojson_path = recognition(file)
        return (
            f'The path to the generated zipped gmns file is: `{gmns_path}`. '
            f'The path to the generated GeoJSON network file is: `{geojson_path}`. '
            f'The path to the visual representation of the recognized road network is: `{best_img_name}`. '
            'Process finished.'
        )
