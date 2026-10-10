"""Read-only recorded frames. No movement, routing or hazard computation."""
import copy
import hashlib
import json
import math
from pathlib import Path


def frame_hash(frame):
    data = {k: v for k, v in frame.items() if k != 'snapshot_hash'}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def valid_lonlat(point):
    if not isinstance(point, list) or len(point) != 2:
        raise ValueError('position must be explicit [longitude, latitude]')
    lon, lat = point
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in point):
        raise ValueError('coordinates must be finite numbers')
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError('coordinates out of WGS84 bounds')


class ReplayStore:
    def __init__(self, area_path, replay_path):
        self._area = json.loads(Path(area_path).read_text())
        self._record = json.loads(Path(replay_path).read_text())
        if isinstance(self._area.get('source_manifest'), str):
            manifest_path = Path(area_path).parent / self._area['source_manifest']
            if manifest_path.resolve().is_relative_to(Path(area_path).parent.resolve()) and manifest_path.is_file():
                self._area['source_manifest'] = json.loads(manifest_path.read_text())
        self._frames = self._record.get('frames', [])
        if not self._frames:
            raise ValueError('replay requires recorded frames')
        identity = tuple(self._frames[0].get(k) for k in ('run_id', 'scenario_id'))
        if not all(isinstance(x, str) and x for x in identity):
            raise ValueError('replay identity is missing')
        previous_time = -1
        for i, frame in enumerate(self._frames):
            if tuple(frame.get(k) for k in ('run_id', 'scenario_id')) != identity:
                raise ValueError('replay identity differs between frames')
            time = frame.get('time_s')
            if isinstance(time, bool) or not isinstance(time, (int,float)) or not math.isfinite(time) or time < 0 or time <= previous_time:
                raise ValueError('replay time must be nonnegative and strictly increasing')
            if frame.get('index') != i or not isinstance(frame.get('snapshot_version'), int):
                raise ValueError('frame index or snapshot version invalid')
            previous_time = time
            if frame.get('snapshot_hash') != frame_hash(frame):
                raise ValueError('recorded snapshot hash mismatch')
            if frame.get('mode') != self._record.get('mode'):
                raise ValueError('frame/replay mode mismatch')
            for vehicle in frame.get('vehicles', []):
                valid_lonlat(vehicle['position_lonlat'])
                for key in ('route_geometry_lonlat','remaining_path_lonlat','completed_trail_lonlat','old_route_geometry_lonlat'):
                    for p in vehicle.get(key, []): valid_lonlat(p)
            for overlay in frame.get('closures', []) + frame.get('hazards', []):
                for p in overlay.get('geometry_lonlat', []): valid_lonlat(p)
        self._identity = identity

    def bootstrap(self):
        return copy.deepcopy({'mode':self._record['mode'], 'label':self._record['label'], 'area':self._area,
            'replay':{'run_id':self._identity[0], 'scenario_id':self._identity[1], 'frame_count':len(self._frames),
            'frame_times_s':[f['time_s'] for f in self._frames], 'description':self._record.get('description','')}})

    def frame(self, index):
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError('frame index must be an integer')
        if not 0 <= index < len(self._frames):
            raise IndexError('frame index out of range')
        return copy.deepcopy(self._frames[index])

    def coverage(self, lat, lon):
        valid_lonlat([lon,lat])
        def contains(bounds):
            west,south,east,north=bounds
            return west <= lon <= east and south <= lat <= north
        in_extent=contains(self._area['bbox_lonlat'])
        in_area=contains(self._area.get('coverage_bbox_lonlat',self._area['bbox_lonlat']))
        layers=copy.deepcopy(self._area.get('coverage',[]))
        available=in_area and any(c.get('status')=='available' for c in layers)
        if in_area:
            label=self._area['label']
            message=('Selected acquisition area dataset available; inspect individual layer coverage.' if available else
                     'The selected area exists, but no geographic layers are available.')
        elif in_extent:
            label=self._area['label']+' (source geometry extent)'
            for layer in layers:
                if layer.get('status')=='available':
                    layer['status']='unknown'
                    layer['detail']='Within the source geometry bounding box, outside acquisition bounds; local data coverage unverified.'
            message='Within the source geometry bounding box, which includes partial OSM way context. This location is outside acquisition bounds; local data coverage is unverified.'
        else:
            label='Unloaded area'
            layers=[{'layer':layer,'status':'unavailable','detail':'No data ingested for this location'}
                    for layer in ('roads','buildings','landuse','terrain','fuels','current_fire')]
            message='Worldwide coordinate selection is supported. This location has no loaded simulation data.'
        return copy.deepcopy({'available':available,'in_loaded_area':in_area,'in_loaded_extent':in_extent,
            'area_id':self._area['area_id'] if in_extent else None,'label':label,'coverage':layers,'message':message})
