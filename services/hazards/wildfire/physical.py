"""Pinned Pyretechnics surface-fire adapter for hypothetical metric grids.

The physical engine is optional and never replaced by the training graph here.
Pyretechnics times are minutes; the public adapter uses seconds.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.machinery
import importlib.metadata
import math
import struct


VERSION = '2026.8.10'
SOURCE_SHA256 = '37aa56941e5d4d6bb2f4119ecbee92e1b32508354cc6c1535898f3b2c665ba66'
NONBURNABLE = frozenset({91, 92, 93, 98, 99})
SUPPORTED_FUELS = frozenset({101, 102}) | NONBURNABLE


class BackendUnavailable(RuntimeError):
    """Exact compiled Pyretechnics runtime is not installed or importable."""


def _engine():
    try:
        installed = importlib.metadata.version('pyretechnics')
    except importlib.metadata.PackageNotFoundError as exc:
        raise BackendUnavailable(f'Pyretechnics {VERSION} is not installed') from exc
    if installed != VERSION:
        raise BackendUnavailable(f'Pyretechnics {VERSION} required; installed {installed}')
    try:
        from pyretechnics import eulerian_level_set as els
        from pyretechnics.space_time_cube import SpaceTimeCube
    except ImportError as exc:
        raise BackendUnavailable(f'Pyretechnics {VERSION} cannot import: {exc}') from exc
    path = getattr(els, '__file__', '') or ''
    if not any(path.endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES):
        raise BackendUnavailable('Pyretechnics level-set solver must be compiled')
    return els, SpaceTimeCube


def engine_available():
    """True only for the exact compiled and importable pinned distribution."""
    try:
        _engine()
    except BackendUnavailable:
        return False
    return True


def _finite(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    if positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(f'{name} is outside its permitted bound')
    _float32(value, name)
    return float(value)


def _float32(value, name):
    """Check engine float32 range, including silent underflow to zero."""
    try:
        rounded = struct.unpack('>f', struct.pack('>f', float(value)))[0]
    except (OverflowError, ValueError) as exc:
        raise ValueError(f'{name} exceeds float32 range') from exc
    if not math.isfinite(rounded) or (value != 0 and rounded == 0):
        raise ValueError(f'{name} cannot be represented as nonzero finite float32')
    return rounded


def _arrival_seconds(raw_minutes, horizon_s):
    """Lower a float32 TOA by one ULP to avoid late road-closure times.

    A solver TOA at the horizon can round slightly above the input's exact
    minute value. Accept one float32 ULP beyond that value, then lower the
    arrival by one ULP and clamp to the public horizon.
    """
    if not math.isfinite(raw_minutes) or raw_minutes < 0:
        raise ValueError('physical solver returned invalid arrival time')
    value = _float32(raw_minutes, 'physical arrival')
    rounded_horizon = _float32(horizon_s / 60.0, 'horizon_minutes')
    horizon_bits = struct.unpack('>I', struct.pack('>f', rounded_horizon))[0]
    upper = struct.unpack('>f', struct.pack('>I', horizon_bits + 1))[0]
    if value > upper:
        raise ValueError('physical solver returned arrival beyond horizon precision')
    if value == 0:
        return 0.0
    bits = struct.unpack('>I', struct.pack('>f', value))[0]
    lower = struct.unpack('>f', struct.pack('>I', bits - 1))[0]
    return max(0.0, min(float(horizon_s), lower * 60.0))


def _validate(config, height, width):
    if not isinstance(config, dict):
        raise ValueError('config must be a dictionary')
    if isinstance(height, bool) or isinstance(width, bool) or not isinstance(height, int) or not isinstance(width, int) or height < 1 or width < 1:
        raise ValueError('positive integer grid dimensions required')
    if height * width > 65536:
        raise ValueError('physical grid exceeds 65536 cells')
    try:
        assumptions = config['physical_assumptions']
        if not isinstance(assumptions, dict) or assumptions['surface_only'] is not True:
            raise ValueError('surface_only=True is required')
        if set(assumptions) != {'surface_only', 'wind_height_m', 'foliar_moisture', 'residence_time_s'}:
            raise ValueError('unsupported or missing physical assumption')
        if _finite(assumptions['wind_height_m'], 'wind_height_m', positive=True) != 10.0:
            raise ValueError('wind_height_m must be 10')
        _finite(assumptions['foliar_moisture'], 'foliar_moisture', nonnegative=True)
        _finite(assumptions['residence_time_s'], 'residence_time_s', positive=True)
        grid = config['grid']
        _finite(grid['cell_size_m'], 'cell_size_m', positive=True)
        for name in ('fuel_model', 'slope_rise_run', 'aspect_deg'):
            matrix = grid[name]
            if not isinstance(matrix, list) or len(matrix) != height or any(not isinstance(row, list) or len(row) != width for row in matrix):
                raise ValueError(f'{name} must match grid shape')
            for row in matrix:
                for value in row:
                    if name == 'fuel_model':
                        if isinstance(value, bool) or not isinstance(value, int) or value not in SUPPORTED_FUELS:
                            raise ValueError(f'unsupported fuel code {value}')
                    elif name == 'slope_rise_run':
                        _finite(value, name, nonnegative=True)
                    elif not 0 <= _finite(value, name) < 360:
                        raise ValueError('aspect_deg must be [0,360)')
        weather = config['weather']
        for name in ('wind_east_m_s', 'wind_north_m_s'):
            _finite(weather[name], name)
        _finite(math.hypot(weather['wind_east_m_s'], weather['wind_north_m_s']) * 3.6,
                'converted wind_speed_10m_km_h', nonnegative=True)
        for name in ('moisture_dead_1hr', 'moisture_dead_10hr', 'moisture_dead_100hr',
                     'moisture_live_herbaceous', 'moisture_live_woody'):
            _finite(weather[name], name, nonnegative=True)
        if _finite(config['horizon_s'], 'horizon_s', positive=True) > 604800:
            raise ValueError('physical horizon exceeds seven days')
        _finite(config['horizon_s'] / 60.0, 'horizon_minutes', positive=True)
        if not isinstance(config['ignitions'], list) or not config['ignitions']:
            raise ValueError('at least one ignition required')
        for ignition in config['ignitions']:
            y, x = ignition['row'], ignition['col']
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (y, x)) or not 0 <= y < height or not 0 <= x < width:
                raise ValueError('ignition outside grid')
            if grid['fuel_model'][y][x] in NONBURNABLE:
                raise ValueError('ignition on nonburnable fuel')
            if _finite(ignition['time_s'], 'ignition time', nonnegative=True) != 0:
                raise ValueError('timed ignitions are unsupported by this physical backend')
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f'missing or malformed physical input: {exc}') from exc
    return assumptions


def physical_arrivals(config, height, width):
    """Return (arrival seconds or None matrix, provenance) for surface fire."""
    assumptions = _validate(config, height, width)
    els, Cube = _engine()
    import numpy as np
    # Lazy import avoids the adapter's physical-backend import cycle.
    from .adapter import wind_to_pyre

    grid, weather = config['grid'], config['weather']
    wind_speed, wind_from = wind_to_pyre(weather['wind_east_m_s'], weather['wind_north_m_s'])
    _finite(wind_speed, 'converted wind_speed_10m_km_h', nonnegative=True)
    shape = (2, height, width)
    horizon_minutes = float(config['horizon_s']) / 60.0
    resolution = (horizon_minutes, float(grid['cell_size_m']), float(grid['cell_size_m']))
    cubes = {
        'slope': Cube(shape, np.asarray(grid['slope_rise_run'], dtype=np.float32)),
        'aspect': Cube(shape, np.asarray(grid['aspect_deg'], dtype=np.float32)),
        'fuel_model': Cube(shape, np.asarray(grid['fuel_model'], dtype=np.float32)),
        'canopy_cover': Cube(shape, 0.0),
        'canopy_height': Cube(shape, 0.0),
        'canopy_base_height': Cube(shape, 0.0),
        'canopy_bulk_density': Cube(shape, 0.0),
        'wind_speed_10m': Cube(shape, wind_speed),
        'upwind_direction': Cube(shape, wind_from),
        'foliar_moisture': Cube(shape, assumptions['foliar_moisture']),
    }
    for name in ('moisture_dead_1hr', 'moisture_dead_10hr', 'moisture_dead_100hr',
                 'moisture_live_herbaceous', 'moisture_live_woody'):
        cubes['fuel_' + name] = Cube(shape, weather[name])
    state = els.SpreadState(shape).set_resolution(resolution)
    ignited = {(item['row'], item['col']) for item in config['ignitions']}
    for cell in sorted(ignited):
        state.ignite_cell(cell)
    state.set_start_time(0.0)
    result = els.spread_fire_with_phi_field(
        cubes, state, resolution, 0.0, horizon_minutes,
        max_cells_per_timestep=0.4, buffer_width=3, use_wind_limit=True,
        surface_lw_ratio_model='rothermel', spot_ignitions={}, spot_config=None)
    matrices = result['spread_state'].get_full_matrices(['fire_type', 'time_of_arrival'])
    fire_type, toa = matrices['fire_type'], matrices['time_of_arrival']
    if fire_type.shape != (height, width) or toa.shape != (height, width):
        raise ValueError('physical solver returned incorrect grid shape')
    arrivals = []
    boundary_reached = False
    for y in range(height):
        row = []
        for x in range(width):
            if (y, x) in ignited:
                row.append(0.0)
            elif grid['fuel_model'][y][x] in NONBURNABLE or int(fire_type[y, x]) == 0:
                row.append(None)
            else:
                row.append(_arrival_seconds(float(toa[y, x]), float(config['horizon_s'])))
            if row[-1] is not None and (y in (0, height - 1) or x in (0, width - 1)):
                boundary_reached = True
        arrivals.append(row)
    try:
        with open(els.__file__, 'rb') as binary:
            solver_sha256 = hashlib.file_digest(binary, 'sha256').hexdigest()
    except OSError as exc:
        raise BackendUnavailable('compiled Pyretechnics solver cannot be hashed') from exc
    provenance = {
        'model_name': 'Pyretechnics surface Rothermel level-set',
        'model_version': VERSION,
        'runtime_distribution_version': importlib.metadata.version('pyretechnics'),
        'compiled_solver_sha256': solver_sha256,
        'physical_engine_implemented': True,
        'scenario_kind': 'hypothetical', 'current_incident': False,
        'seed': config['seed'],
        'seed_usage': 'recorded; no spotting or stochastic process',
        'source_ledger': copy.deepcopy(config['source_ledger']),
        'physical_assumptions': copy.deepcopy(assumptions),
        'wind_speed_10m_km_h': wind_speed,
        'upwind_direction_deg_from_cw_north': wind_from,
        'solver_settings': {'surface_lw_ratio_model': 'rothermel',
                            'max_cells_per_timestep': 0.4, 'buffer_width': 3,
                            'use_wind_limit': True, 'spotting': False,
                            'time_band_duration_min': horizon_minutes,
                            'stop_time_min': float(result['stop_time']),
                            'stop_condition': result['stop_condition'],
                            'boundary_reached': boundary_reached},
        'expected_source_archive_sha256': SOURCE_SHA256,
        'model_reference': 'https://github.com/pyregence/pyretechnics/tree/2026.8.10',
        'limitations': ['Hypothetical, uncalibrated inputs; no current incident evidence.',
                        'Static fuels, weather and slope; surface fire only, no spotting, crown fire, suppression, structures or atmospheric feedback.',
                        'The modeled domain is a hard boundary; fire cannot propagate beyond it.',
                        'Active flame residence time is assumed from physical_assumptions, not an engine output.',
                        'Float32 arrival timestamps are lowered by one ULP before conversion to seconds for conservative timing.',
                        'Null arrival means not reached within this modeled horizon; never safe forever.'],
    }
    return arrivals, provenance
