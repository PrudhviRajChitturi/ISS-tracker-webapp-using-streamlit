import streamlit as st
import requests
from skyfield.api import load, EarthSatellite, Topos
import datetime # Make sure datetime module is imported
from datetime import timedelta
import time
import folium
from streamlit_folium import folium_static
import pandas as pd
import numpy as np

# --- Global variables and initial setup ---
# Load timescale. This is typically done once.
ts = load.timescale()
iss_satellite = None

# Determine the local timezone once
# This is generally the safest way to get the system's local timezone
local_tz = datetime.datetime.now().astimezone().tzinfo


@st.cache_data(ttl=3600)  # Cache TLE for 1 hour to reduce API calls to Celestrak
def fetch_iss_tle_cached():
    """
    Fetches the latest Two-Line Element (TLE) data for the ISS from Celestrak.
    This function is cached to avoid frequent external API calls.
    """
    url = "https://celestrak.org/NORAD/elements/stations.txt"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        lines = response.text.splitlines()

        iss_tle_lines = []
        for i in range(len(lines)):
            # "ISS (ZARYA)" is the common name in Celestrak's stations.txt for the ISS
            if "ISS (ZARYA)" in lines[i]:
                iss_tle_lines.append(lines[i].strip())
                iss_tle_lines.append(lines[i + 1].strip())
                iss_tle_lines.append(lines[i + 2].strip())
                break

        if len(iss_tle_lines) == 3:
            return iss_tle_lines[0], iss_tle_lines[1], iss_tle_lines[2]
        else:
            st.error("ISS TLE data not found in the response from Celestrak.")
            return None, None, None

    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching TLE data from Celestrak: {e}")
        return None, None, None


def get_iss_current_location(satellite_obj):
    """
    Calculates the current latitude and longitude of the ISS.
    """
    if satellite_obj is None:
        return None, None
    t = ts.now()
    geocentric = satellite_obj.at(t)

    # Corrected line: Get the GeographicPosition object first
    subpoint = geocentric.subpoint()

    # Then access its attributes for lat, lon, and elevation
    lat = subpoint.latitude.degrees
    lon = subpoint.longitude.degrees
    # You can also get elevation if needed, but for this function, we only return lat/lon
    # elevation = subpoint.elevation.km

    return lat, lon


def calculate_iss_passes_for_location(satellite_obj, latitude, longitude, elevation_m=0, days_ahead=2):
    """
    Calculates and returns the next ISS pass times for a given location using Skyfield.
    """
    if satellite_obj is None:
        return []

    observer = Topos(latitude_degrees=latitude, longitude_degrees=longitude, elevation_m=elevation_m)

    t0 = ts.now()
    t1 = ts.utc(t0.utc_datetime() + timedelta(days=days_ahead))

    # Find events (rise, culmination, set) for the given observer and time range
    t, events = satellite_obj.find_events(observer, t0, t1)

    passes = []
    # A full pass consists of three events: rise, culmination, set
    for i in range(len(events)):
        if i % 3 == 0 and i + 2 < len(events):
            rise_time = t[i].astimezone(local_tz)
            culmination_time = t[i + 1].astimezone(local_tz)
            set_time = t[i + 2].astimezone(local_tz)

            duration_seconds = (set_time - rise_time).total_seconds()
            duration_minutes = duration_seconds / 60

            # Calculate peak altitude at culmination
            alt, az, distance = (satellite_obj - observer).at(t[i + 1]).altaz()
            peak_altitude = alt.degrees

            passes.append({
                "Rise Time": rise_time.strftime('%Y-%m-%d %H:%M:%S %Z%z'),
                "Culmination Time": culmination_time.strftime('%Y-%m-%d %H:%M:%S %Z%z'),
                "Set Time": set_time.strftime('%Y-%m-%d %H:%M:%S %Z%z'),
                "Peak Altitude (deg)": f"{peak_altitude:.2f}",
                "Duration (min)": f"{duration_minutes:.2f}"
            })
    return passes


# --- Streamlit App ---
st.set_page_config(page_title="ISS Live Tracker", layout="wide")

st.title("🛰️ Live International Space Station (ISS) Tracker")
st.markdown("Track the ISS in real-time and predict its passes over your location!")

# Fetch TLE data once at the start and create the satellite object
name, line1, line2 = fetch_iss_tle_cached()
if name and line1 and line2:
    iss_satellite = EarthSatellite(line1, line2, name, ts)
else:
    st.error("Could not initialize ISS tracking due to TLE fetch failure. Please refresh.")

# Current ISS Location Section
st.subheader("Current ISS Location")
if iss_satellite:
    current_lat, current_lon = get_iss_current_location(iss_satellite)
    if current_lat is not None and current_lon is not None:
        st.write(f"**Latitude:** `{current_lat:.4f}` **Longitude:** `{current_lon:.4f}`")

        # Create a Folium map centered on the current ISS location
        m = folium.Map(location=[current_lat, current_lon], zoom_start=2)
        folium.Marker(
            location=[current_lat, current_lon],
            tooltip=f"ISS @ {current_lat:.2f}, {current_lon:.2f}",
            icon=folium.Icon(color='red', icon='satellite', prefix='fa')
        ).add_to(m)

        # Plot ground track for next 90 minutes
        minutes_ahead = 90

        # Corrected: Create Skyfield time objects for the sequence directly.
        t_start = ts.now()  # Get the current Skyfield time object
        times = t_start + np.arange(0, minutes_ahead, 5) / (24 * 60)  # Add minutes in days

        geocentric_points = iss_satellite.at(times)

        # Corrected approach for getting arrays of lat/lon from multiple points:
        subpoints = geocentric_points.subpoint()  # This returns a GeographicPosition object for each time
        latitudes = subpoints.latitude.degrees
        longitudes = subpoints.longitude.degrees
        # If you needed elevations, you would get them as:
        # elevations = subpoints.elevation.km

        # Adjust longitudes to wrap around for continuous path visualization over the map boundary
        wrapped_longitudes = [longitudes[0]]
        for i in range(1, len(longitudes)):
            diff = longitudes[i] - longitudes[i - 1]
            if diff > 180:
                wrapped_longitudes.append(longitudes[i] - 360)
            elif diff < -180:
                wrapped_longitudes.append(longitudes[i] + 360)
            else:
                wrapped_longitudes.append(longitudes[i])

        points = list(zip(latitudes, wrapped_longitudes))
        folium.PolyLine(points, color='blue', weight=2.5, opacity=1).add_to(m)

        # Display the map in Streamlit
        folium_static(m, width=700, height=500)
    else:
        st.warning("Could not retrieve current ISS location.")
else:
    st.info("Waiting for ISS TLE data to load...")

# ISS Pass Prediction Section
st.subheader("Predict ISS Passes Over Your Location\n(Adjust your location latitude and longitude below, default is New Delhi Coordinates)")

col1, col2, col3 = st.columns(3)
with col1:
    # Defaulting to Delhi, India coordinates as per current context.
    user_lat = st.number_input("Your Latitude:", min_value=-90.0, max_value=90.0, value=28.7041, format="%.4f")
with col2:
    user_lon = st.number_input("Your Longitude:", min_value=-180.0, max_value=180.0, value=77.1025, format="%.4f")
with col3:
    days_to_predict = st.slider("Days to Predict:", min_value=1, max_value=7, value=2)

if st.button("Predict Passes"):
    if iss_satellite:
        with st.spinner(f"Calculating passes for {days_to_predict} days..."):
            passes = calculate_iss_passes_for_location(iss_satellite, user_lat, user_lon, days_ahead=days_to_predict)
            if passes:
                st.success(
                    f"Found {len(passes)} passes for Lat: {user_lat:.4f}, Lon: {user_lon:.4f} in the next {days_to_predict} days.")
                passes_df = pd.DataFrame(passes)
                st.dataframe(passes_df)
            else:
                st.info(
                    f"No ISS passes predicted for Lat: {user_lat:.4f}, Lon: {user_lon:.4f} in the next {days_to_predict} days.")
    else:
        st.warning("ISS satellite data not loaded. Please refresh the page.")

st.markdown("---")
st.markdown("Developed for INDIA SPACE ACADEMY SUMMER SCHOOL PROJECT by Prudhvi Raj Ch.")