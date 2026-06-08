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

    # itrs.spherical.lat/lon jeosentrik açılardır (Dünya'yı küre kabul eder).
    # WGS84 elipsoidine göre gerçek jeodezik enlem/boylam/yükseklik için
    # EarthLocation üzerinden dönüşüm yapıyoruz — bu hem altitude'daki
    # ~7 km'lik küresel-yarıçap yaklaşıklığını giderir hem de yer izini
    # haritalarda kullanılan standart (jeodezik) referansla hizalar.
    location = EarthLocation.from_geocentric(itrs.x, itrs.y, itrs.z)
    geodetic = location.to_geodetic()

    lat = geodetic.lat.to(u.deg).value
    # Boylamı [-180, 180] aralığına sarıyoruz: astropy varsayılan olarak
    # [0, 360) döndürür, bu da gerçek 180. meridyen yerine 0/360 sınırında
    # sahte bir süreksizlik yaratıp haritayı boydan boya kesen çizgilere yol açıyordu.
    lon = geodetic.lon.wrap_at(180 * u.deg).to(u.deg).value
    alt_km = geodetic.height.to(u.km).value
    return lat, lon, alt_km
