
import pandas as pd

def test_inventory_file_exists_and_columns():
    df = pd.read_csv('inventory.csv', encoding='windows-1256')
    cols = [c.lower().replace(' ', '').replace('_', '') for c in df.columns]
    assert 'barcode' in cols
    assert 'name' in cols
    assert any('qty' in c for c in cols)
