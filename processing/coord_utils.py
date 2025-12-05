import numpy as np
from astropy.time import Time
from astropy import units as u
from astropy.coordinates import CartesianRepresentation, TEME, ITRS, EarthLocation, GCRS
from datetime import datetime, timezone


def teme_pos_to_latlon(r_km, time_utc: datetime):
    """
    :param r_km: 3 kayan noktalı iteratif değer (TEME koardinatları km cinsinden)
    :param time_utc: UTC sisteminde tarih saat
    :return: lat_deg, lon_deg, alt_km
    """
    # astropy metre cinsinden değer bekler
    r_m = [x * 1000.0 for x in r_km]
    t = Time(time_utc.strftime('%Y-%m-%dT%H:%M:%S.%f'), format="isot", scale="utc")
    #t = Time(time_utc.isoformat(), format="isot", scale="utc")
    vec = CartesianRepresentation(r_m * u.m)
    teme_coord = TEME(vec, obstime=t)
    itrs = teme_coord.transform_to(ITRS(obstime=t))
    lat = itrs.spherical.lat.to(u.deg).value
    lon = itrs.spherical.lon.to(u.deg).value
    alt_m = itrs.spherical.distance.to(u.m).value - 6371000.0  # yaklaşık Dünya yarıçapını çıkar
    return lat, lon, alt_m / 1000.0
