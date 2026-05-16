from pathlib import Path
from rosbags.highlevel import AnyReader # pip install rosbags
# import soundfile as sf
import numpy as np
from tqdm import tqdm
import pickle

topics = [
    '/audio1/audio',
    '/audio2/audio',
    '/audio3/audio',
    '/audio4/audio',
]
def export_rosbag(bag_path, bag_name):
    dots_cnt = 0
    result = {topic: [] for topic in topics}
    print("Opening BAG file")
    with open('dbg.mp3', 'wb') as faudio1:
        with AnyReader([bag_path/bag_name]) as reader:
            connections = [x for x in reader.connections if x.topic in topics]
            print("Starting reading...")
            for connection, timestamp, rawdata in reader.messages(connections=connections):
                msg = reader.deserialize(rawdata, connection.msgtype)
                print('.', end=('\n' if dots_cnt % 100 == 0 else ''))
                dots_cnt += 1
                if connection.topic == '/audio1/audio':
                    faudio1.write(bytes(msg.data))
                result[connection.topic].append({'timestamp': timestamp, 'msg': msg.data})
        print("Writing to file...")
    pickle.dump(result, open(bag_name.name[:-4] + '.pkl', 'wb'))

if __name__ == '__main__':
    export_rosbag(Path("/experiments"), Path("Mavic3.bag"))
    export_rosbag(Path("/experiments"), Path("Mavic2.bag"))
    export_rosbag(Path("/experiments"), Path("M300.bag"))
    export_rosbag(Path("/experiments"), Path("Pham4.bag"))
    export_rosbag(Path("/experiments"), Path("Avata.bag"))
