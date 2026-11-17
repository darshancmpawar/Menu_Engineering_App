"""Flavoured Rice is every rice except plain rice, which is the Steamed Rice row.

The `rice` course type IS the Flavoured Rice row in every city (north, south and
continental rice, noodles, pasta). Plain rice reaches that row unless it is in
`RICE_EXCLUDE_ITEMS`, and four plain rices filed under other sub-categories were
not (boiled, white boiled, plain basmati, jasmine). `item_style` names them.
"""

import pandas as pd

from src.constants import RICE_EXCLUDE_ITEMS
from src.ontology.paths import city_excel_path


def test_every_plain_rice_is_kept_out_of_flavoured_rice():
    df = pd.read_excel(city_excel_path('Bangalore'))
    plain = df[(df['course_type'] == 'rice') & (df['item_style'] == 'plain_rice')]
    assert len(plain), 'no plain_rice style left: this check has gone vacuous'
    leaked = sorted(set(plain['item']) - RICE_EXCLUDE_ITEMS)
    assert not leaked, f'plain rice that can be served as Flavoured Rice: {leaked}'
