from pathlib import Path
from rosbags.highlevel import AnyReader # pip install rosbags
import numpy as np
from tqdm import tqdm
import pickle

topics = [
    '/leica/point/relative',
]
def export_rosbag(bag_path, bag_name):
    dots_cnt = 0
    result = {topic: [] for topic in topics}
    print("Opening BAG file")
    with AnyReader([bag_path/bag_name]) as reader:
        connections = [x for x in reader.connections if x.topic in topics]
        print("Starting reading...")
        for connection, timestamp, rawdata in reader.messages(connections=connections):
            msg = reader.deserialize(rawdata, connection.msgtype)
            print('.', end=('\n' if dots_cnt % 100 == 0 else ''))
            dots_cnt += 1
            result[connection.topic].append({'timestamp': timestamp, 'x': msg.point.x, 'y': msg.point.y, 'z': msg.point.z})
        print("Writing to file...")
    pickle.dump(result, open(bag_name.name[:-4] + '_gt.pkl', 'wb'))

if __name__ == '__main__':
    export_rosbag(Path("D:\\MMAUD\\Ground_truth"), Path("2023-08-24-11-14-40_mavic3.bag"))
