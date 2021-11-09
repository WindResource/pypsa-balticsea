"""
Build import locations for fossil gas from entry-points, LNG terminals and production sites.
"""

import logging
logger = logging.getLogger(__name__)

import pandas as pd
import geopandas as gpd


def read_scigrid_gas(fn):
    df = gpd.read_file(fn)
    df = pd.concat([df, df.param.apply(pd.Series)], axis=1)
    df.drop(["param", "uncertainty", "method"], axis=1, inplace=True)
    return df


def build_gas_input_locations(lng_fn, entry_fn, prod_fn, countries):
    
    # LNG terminals
    lng = read_scigrid_gas(lng_fn)

    # Entry points from outside the model scope
    entry = read_scigrid_gas(entry_fn)
    entry["from_country"] = entry.from_country.str.rstrip()
    entry = entry.loc[
        ~(entry.from_country.isin(countries) & entry.to_country.isin(countries)) &  # only take non-EU entries
        ~entry.name.str.contains("Tegelen") |  # malformed datapoint
        (entry.from_country == "NO")  # entries from NO to GB
    ]

    # production sites inside the model scope
    prod = read_scigrid_gas(prod_fn)
    prod = prod.loc[
        (prod.geometry.y > 35) &
        (prod.geometry.x < 30) &
        (prod.country_code != "DE")
    ]

    lng["mcm_per_day"] = lng["max_cap_store2pipe_M_m3_per_d"]
    entry["mcm_per_day"] = entry["max_cap_from_to_M_m3_per_d"]
    prod["mcm_per_day"] = prod["max_supply_M_m3_per_d"]

    lng["type"] = "lng"
    entry["type"] = "entry"
    prod["type"] = "production"

    sel = ["geometry", "mcm_per_day", "type"]

    return pd.concat([prod[sel], entry[sel], lng[sel]], ignore_index=True)


if __name__ == "__main__":

    if 'snakemake' not in globals():
        from helper import mock_snakemake
        snakemake = mock_snakemake(
            'build_gas_import_locations',
            simpl='',
            clusters='37',
        )

    logging.basicConfig(level=snakemake.config['logging_level'])

    onshore_regions = gpd.read_file(snakemake.input.regions_onshore).set_index('name')

    countries = onshore_regions.index.str[:2].unique().str.replace("GB", "UK")

    gas_input_locations = build_gas_input_locations(
        snakemake.input.lng,
        snakemake.input.entry,
        snakemake.input.production,
        countries
    )

    # recommended to use projected CRS rather than geographic CRS
    gas_input_nodes = gpd.sjoin_nearest(
        gas_input_locations.to_crs(3035),
        onshore_regions.to_crs(3035),
        how='left'
    )

    gas_input_nodes.rename(columns={"index_right": "bus"}, inplace=True)

    gas_input_nodes.to_file(snakemake.output.gas_input_nodes, driver='GeoJSON')

    gas_input_nodes_s = gas_input_nodes.groupby(["bus", "type"])["mcm_per_day"].sum().unstack()
    gas_input_nodes_s.columns.name = "mcm_per_day"

    gas_input_nodes_s.to_csv(snakemake.output.gas_input_nodes_simplified)