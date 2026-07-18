# barcode_streamlit_app.py
import streamlit as st
import pandas as pd
import os
import shutil
import tempfile
import threading
from datetime import datetime

try:
    from filelock import FileLock
except ImportError:
    # Fallback no-op-ish lock if the `filelock` package isn't installed.
    # Install the real thing with: pip install filelock
    # This fallback only protects against races within a single process
    # (e.g. multiple browser tabs hitting the same Streamlit server) —
    # it will NOT protect against races across multiple processes/machines.
    class FileLock:
        _local_lock = threading.Lock()

        def __init__(self, path, timeout=10):
            self.path = path
            self.timeout = timeout

        def __enter__(self):
            self._local_lock.acquire()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self._local_lock.release()
            return False

INVENTORY_PATH = "inventory.csv"
LOCK_PATH = "inventory.csv.lock"
BACKUP_PATH = "inventory.csv.bak"

# Set page configuration
st.set_page_config(
    page_title="Barcode Scanner Inventory_2",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)


class SessionCounter:
    """Class to track session statistics"""
    def __init__(self):
        if 'session_total' not in st.session_state:
            st.session_state.session_total = 0
        if 'scanned_items' not in st.session_state:
            st.session_state.scanned_items = []
        if 'session_start_time' not in st.session_state:
            st.session_state.session_start_time = datetime.now()

    def add_item(self, barcode, product_name, old_qty, new_qty, action='scan'):
        """Add an item to session counter"""
        st.session_state.session_total += 1
        st.session_state.scanned_items.append({
            'barcode': barcode,
            'product_name': product_name,
            'old_qty': old_qty,
            'new_qty': new_qty,
            'action': action,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    def get_session_total(self):
        """Get total items scanned in this session"""
        return st.session_state.session_total

    def get_session_duration(self):
        """Get session duration"""
        return datetime.now() - st.session_state.session_start_time

    def reset_session(self):
        """Reset the session"""
        st.session_state.session_total = 0
        st.session_state.scanned_items = []
        st.session_state.session_start_time = datetime.now()


def read_csv_with_encoding(file_path):
    """Read CSV file with Arabic (Windows-1256) encoding.

    Returns a (dataframe, encoding_used) tuple.
    """
    encodings = ['utf-8', 'windows-1256', 'cp1256', 'iso-8859-6', 'latin1', 'cp1252']

    for enc in encodings:
        try:
            # Tier 1: Clean standard parse
            return pd.read_csv(file_path, encoding=enc), enc
        except UnicodeDecodeError:
            continue
        except pd.errors.ParserError as pe:
            # Tier 2: Parser error fallback (Tolerant native Pandas)
            try:
                st.warning(f"ParserError with encoding {enc}: {pe}. Retrying with tolerant parsing.")
                df = pd.read_csv(file_path, encoding=enc, engine='python', on_bad_lines='warn')
                return df, enc
            except Exception:
                pass # Fallthrough directly to Tier 3 manual repair for *this* encoding
            
            # Tier 3: Manual row reconstruction for corrupted structures
            try:
                st.warning(f"ParserError fallback failed for {enc}: attempting row reconstruction.")
                with open(file_path, 'r', encoding=enc, errors='replace') as f:
                    lines = f.readlines()

                if not lines:
                    continue # Skip empty files to next encoding context

                header_line = lines[0].rstrip('\n').strip()
                # Dynamically determine separator if possible, fallback to comma
                delimiter = ';' if ';' in header_line and ',' not in header_line else ','
                header_cols = [c.strip() for c in header_line.split(delimiter)]
                expected = len(header_cols)

                reconstructed = []
                repaired = 0

                for ln in lines[1:]:
                    ln_core = ln.rstrip('\n')
                    parts = ln_core.split(delimiter)

                    if len(parts) == expected:
                        reconstructed.append(parts)
                    elif len(parts) > expected:
                        num_trailing = max(expected - 2, 0)
                        barcode = parts[0]
                        if num_trailing > 0:
                            trailing = parts[-num_trailing:]
                            name_parts = parts[1:len(parts) - num_trailing]
                        else:
                            trailing = []
                            name_parts = parts[1:]

                        name = delimiter.join(name_parts).strip()
                        new_row = [barcode, name] + trailing
                        while len(new_row) < expected:
                            new_row.append('')
                        reconstructed.append(new_row)
                        repaired += 1
                    else:
                        new_row = parts + [''] * (expected - len(parts))
                        reconstructed.append(new_row)

                df = pd.DataFrame(reconstructed, columns=header_cols)
                st.info(f"Reconstructed CSV with encoding {enc}. Repaired {repaired} lines.")
                return df, enc
            except Exception as e:
                st.error(f"Row reconstruction completely failed for encoding {enc}: {e}")
                continue
        except Exception:
            continue

    raise Exception("Could not read the CSV file with any supported encoding or parsing strategy")

def normalize_column_names(df):
    """Normalize column names to handle different cases and spaces.

    Warns (instead of silently overwriting) if two columns normalize to the
    same key, e.g. 'Qty New' and 'QtyNew' — that's a real data-mapping bug
    if it happens, not something to swallow quietly.
    """
    column_mapping = {}
    collisions = []
    for col in df.columns:
        normalized = col.lower().replace(' ', '').replace('_', '')
        if normalized in column_mapping and column_mapping[normalized] != col:
            collisions.append((column_mapping[normalized], col))
        else:
            column_mapping[normalized] = col

    for existing, ignored in collisions:
        st.warning(
            f"Column name collision: '{existing}' and '{ignored}' both normalize to the "
            f"same key. '{ignored}' will be ignored — please rename one of them in your CSV."
        )
    return column_mapping


def _file_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def load_inventory_df(force_reload=False):
    """Load inventory.csv, cached in session_state and only re-read from
    disk when the file's mtime has changed (or force_reload=True).

    This avoids re-running the full encoding-detection ladder on every
    single widget interaction (e.g. every keystroke in a search box).
    """
    if not os.path.exists(INVENTORY_PATH):
        st.error(f"File '{INVENTORY_PATH}' not found!")
        return None

    current_mtime = _file_mtime(INVENTORY_PATH)
    cached_mtime = st.session_state.get('inventory_mtime')
    cached_df = st.session_state.get('inventory_df')

    if (not force_reload) and cached_df is not None and cached_mtime == current_mtime:
        return cached_df.copy()

    try:
        df, encoding_used = read_csv_with_encoding(INVENTORY_PATH)
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return None

    st.session_state['inventory_df'] = df
    st.session_state['inventory_mtime'] = current_mtime
    st.session_state['inventory_encoding'] = encoding_used
    return df.copy()


def _atomic_write_csv(df, encoding):
    """Write df to INVENTORY_PATH atomically, with a rotating backup.

    Caller MUST already hold the FileLock — this function does no locking
    itself so it can safely be called from inside a larger locked
    read-modify-write transaction (see scan_barcode) without deadlocking.
    """
    if os.path.exists(INVENTORY_PATH):
        try:
            shutil.copyfile(INVENTORY_PATH, BACKUP_PATH)
        except OSError as e:
            st.warning(f"Could not create backup before saving: {e}")

    dir_name = os.path.dirname(os.path.abspath(INVENTORY_PATH)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".csv.tmp")
    os.close(fd)
    try:
        df.to_csv(tmp_path, index=False, encoding=encoding)
    except UnicodeEncodeError as e:
        os.remove(tmp_path)
        st.error(
            f"Could not encode data as {encoding}: {e}. Some characters in your "
            "data may not be representable in this encoding. Consider re-saving "
            "inventory.csv as UTF-8."
        )
        return False

    os.replace(tmp_path, INVENTORY_PATH)  # atomic on POSIX and Windows
    return True


def save_inventory_data(df):
    """Acquire the lock and atomically save inventory data, preserving the
    encoding it was originally read with (instead of hardcoding one)."""
    encoding = st.session_state.get('inventory_encoding', 'windows-1256')
    try:
        with FileLock(LOCK_PATH, timeout=10):
            ok = _atomic_write_csv(df, encoding)
        if ok:
            st.session_state['inventory_df'] = df
            st.session_state['inventory_mtime'] = _file_mtime(INVENTORY_PATH)
        return ok
    except Exception as e:
        st.error(f"Error saving file: {e}")
        return False


def scan_barcode(barcode_col, qty_col, qty_new_col, name_col, barcode_input, session_counter, action='scan'):
    """Increment the scanned quantity for barcode_input as a single locked
    transaction: reload the freshest copy of inventory.csv from disk,
    update it, and save — all under one lock. This closes the
    read-modify-write race that would otherwise let two near-simultaneous
    scans (different tabs / scanning stations) silently overwrite each
    other's update.

    Returns:
        "not_found"                  if the barcode isn't in inventory
        (updated_row, new_qty)       on success
        None                         on a read/write error (already shown to user)
    """
    try:
        with FileLock(LOCK_PATH, timeout=10):
            try:
                df, encoding_used = read_csv_with_encoding(INVENTORY_PATH)
            except Exception as e:
                st.error(f"Error reading file: {e}")
                return None
            st.session_state['inventory_encoding'] = encoding_used

            df[barcode_col] = df[barcode_col].astype(str)
            matching_rows = df[df[barcode_col] == barcode_input]
            if matching_rows.empty:
                return "not_found"

            current_value = df.loc[df[barcode_col] == barcode_input, qty_new_col].iloc[0]
            if pd.isna(current_value):
                new_value = 1
            else:
                try:
                    new_value = int(current_value) + 1
                except (ValueError, TypeError):
                    new_value = 1

            df.loc[df[barcode_col] == barcode_input, qty_new_col] = new_value
            updated_product = df[df[barcode_col] == barcode_input].iloc[0].copy()

            if not _atomic_write_csv(df, encoding_used):
                return None

        # Update the in-memory cache outside the lock (cheap, no disk I/O)
        st.session_state['inventory_df'] = df
        st.session_state['inventory_mtime'] = _file_mtime(INVENTORY_PATH)

        session_counter.add_item(
            barcode=updated_product[barcode_col],
            product_name=updated_product.get(name_col, ""),
            old_qty=updated_product.get(qty_col, 0),
            new_qty=new_value,
            action=action
        )
        return updated_product, new_value
    except Exception as e:
        st.error(f"Error updating inventory: {e}")
        return None


def single_scan_mode(session_counter):
    """Single barcode scan mode"""
    st.header("📱 Single Scan Mode")

    df = load_inventory_df()
    if df is None:
        return

    column_mapping = normalize_column_names(df)

    required_columns = ['barcode', 'name', 'qty', 'qtynew']
    missing_columns = [col for col in required_columns if col not in column_mapping]
    if missing_columns:
        st.error(f"Missing columns: {missing_columns}")
        st.info("Please ensure your CSV has columns for barcode, name, quantity, and new quantity")
        return

    barcode_col = column_mapping['barcode']
    name_col = column_mapping['name']
    qty_col = column_mapping['qty']
    qty_new_col = column_mapping['qtynew']

    # A form with clear_on_submit=True clears the input automatically after
    # each scan — no more manual session_state clear-flag bookkeeping.
    with st.form("single_scan_form", clear_on_submit=True):
        col1, col2 = st.columns([2, 1])
        with col1:
            barcode_input = st.text_input(
                "Scan or enter barcode:",
                placeholder="Scan or type barcode and press Enter..."
            )
        with col2:
            st.write("")
            submitted = st.form_submit_button("Scan Item", type="primary", use_container_width=True)

    if submitted:
        barcode_input = str(barcode_input or "").strip()
        if not barcode_input:
            st.warning("Please enter or scan a barcode.")
            return

        result = scan_barcode(barcode_col, qty_col, qty_new_col, name_col, barcode_input, session_counter)

        if result == "not_found":
            st.error(f"Barcode '{barcode_input}' not found in database!")
            with st.expander("Show available barcodes"):
                st.write("First 20 barcodes:")
                st.code(", ".join(df[barcode_col].astype(str).head(20).tolist()))
        elif result is not None:
            updated_product, new_value = result
            st.success("✅ Item scanned successfully!")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Product", updated_product.get(name_col, ""))
            with col2:
                st.metric("Barcode", updated_product[barcode_col])
            with col3:
                try:
                    old_q = int(updated_product.get(qty_col, 0))
                except (ValueError, TypeError):
                    old_q = updated_product.get(qty_col, 0)
                st.metric("Old Quantity", old_q)
            with col4:
                st.metric("New Quantity", int(new_value))


def continuous_scan_mode(session_counter):
    """Continuous scan mode"""
    st.header("🔄 Continuous Scan Mode")

    df = load_inventory_df()
    if df is None:
        return

    column_mapping = normalize_column_names(df)
    if any(k not in column_mapping for k in ['barcode', 'name', 'qty', 'qtynew']):
        st.error("inventory.csv must contain barcode, name, qty and qty_new (or similar) columns to use continuous scan.")
        return

    barcode_col = column_mapping['barcode']
    name_col = column_mapping['name']
    qty_col = column_mapping['qty']
    qty_new_col = column_mapping['qtynew']

    if 'continuous_scan_active' not in st.session_state:
        st.session_state.continuous_scan_active = False

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("🎯 Start Continuous Scan", type="primary", use_container_width=True):
            st.session_state.continuous_scan_active = True
            st.success("Continuous scan mode activated! Scan barcodes below.")
        if st.button("🛑 Stop Continuous Scan", use_container_width=True):
            st.session_state.continuous_scan_active = False
            st.info("Continuous scan mode stopped.")

    if st.session_state.continuous_scan_active:
        st.info("💡 Scan barcodes in the input field below. Press Enter after each scan.")

        with st.form("continuous_scan_form", clear_on_submit=True):
            barcode_input = st.text_input(
                "Scan barcode (press Enter after each scan):",
                placeholder="Scan barcode and press Enter..."
            )
            submitted = st.form_submit_button("Add Scan", use_container_width=True)

        if submitted:
            barcode_input = str(barcode_input or "").strip()
            if barcode_input:
                result = scan_barcode(barcode_col, qty_col, qty_new_col, name_col, barcode_input, session_counter)
                if result == "not_found":
                    st.error(f"Barcode '{barcode_input}' not found!")
                elif result is not None:
                    updated_product, new_value = result
                    st.success(f"✅ Scanned: {updated_product.get(name_col, '')} - New Qty: {new_value}")


def show_session_summary(session_counter):
    """Display session summary"""
    st.header("📊 Session Summary")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Items Scanned", session_counter.get_session_total())
    with col2:
        duration = session_counter.get_session_duration()
        total_seconds = int(duration.total_seconds())  # correct beyond 24h, unlike duration.seconds
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        st.metric("Session Duration", f"{hours}h {minutes}m")
    with col3:
        if st.button("🔄 Reset Session", use_container_width=True):
            session_counter.reset_session()
            st.success("Session reset successfully!")

    if st.session_state.scanned_items:
        st.subheader("📋 Scanned Items")
        summary_df = pd.DataFrame(st.session_state.scanned_items)
        st.dataframe(
            summary_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "timestamp": "Time",
                "barcode": "Barcode",
                "product_name": "Product Name",
                "old_qty": "Old Qty",
                "new_qty": "New Qty",
                "action": "Action"
            }
        )

        csv = summary_df.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="📥 Download Session CSV",
            data=csv,
            file_name=f"scan_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No items scanned in this session yet.")


def inventory_overview():
    """Display inventory overview"""
    st.header("📦 Inventory Overview")

    df = load_inventory_df()
    if df is None:
        return

    column_mapping = normalize_column_names(df)

    if 'qtynew' not in column_mapping:
        st.warning("Inventory is missing a 'qty_new' (scanned quantity) column, so overview stats can't be shown.")
        return

    qty_new_col = column_mapping['qtynew']
    name_col = column_mapping.get('name')
    barcode_col = column_mapping.get('barcode')

    qty_new_numeric = pd.to_numeric(df[qty_new_col], errors='coerce')
    total_scanned = qty_new_numeric.sum() if not qty_new_numeric.isna().all() else 0
    unique_items_scanned = int((qty_new_numeric > 0).sum())

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Products", len(df))
    with col2:
        st.metric("Total Items Scanned", int(total_scanned))
    with col3:
        st.metric("Unique Items Scanned", unique_items_scanned)

    if barcode_col and name_col:
        scanned_items = df[qty_new_numeric > 0]
        if not scanned_items.empty:
            st.subheader("✅ Scanned Items in Inventory")
            display_df = scanned_items[[barcode_col, name_col, qty_new_col]].copy()
            display_df.columns = ['Barcode', 'Product Name', 'Scanned Quantity']
            st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.subheader("🔍 Full Inventory")
    search_term = st.text_input("Search products:", placeholder="Enter product name or barcode...")

    display_full_df = df.copy()
    if search_term and name_col and barcode_col:
        # regex=False: a literal search so parentheses, asterisks, etc. in a
        # barcode or product name don't raise a regex error.
        mask = (
            display_full_df[name_col].astype(str).str.contains(search_term, case=False, na=False, regex=False) |
            display_full_df[barcode_col].astype(str).str.contains(search_term, case=False, na=False, regex=False)
        )
        display_full_df = display_full_df[mask]

    display_columns = [c for c in [barcode_col, name_col, column_mapping.get('qty'), qty_new_col] if c]
    st.dataframe(
        display_full_df[display_columns],
        use_container_width=True,
        hide_index=True,
        height=400
    )


def file_management():
    """File management section"""
    st.header("⚙️ File Management")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Fix File Encoding")
        if st.button("🔧 Fix Encoding to Windows-1256", use_container_width=True):
            if os.path.exists(INVENTORY_PATH):
                try:
                    # Reuse the same tolerant reader used everywhere else,
                    # instead of a bare pd.read_csv that only handles utf-8.
                    df, _ = read_csv_with_encoding(INVENTORY_PATH)
                    with FileLock(LOCK_PATH, timeout=10):
                        saved = _atomic_write_csv(df, 'windows-1256')
                    if saved:
                        st.session_state['inventory_encoding'] = 'windows-1256'
                        st.session_state['inventory_df'] = df
                        st.session_state['inventory_mtime'] = _file_mtime(INVENTORY_PATH)
                        st.success("File encoding fixed to Windows-1256 (Arabic)")
                except Exception as e:
                    st.error(f"Error fixing encoding: {e}")
            else:
                st.error(f"{INVENTORY_PATH} not found!")

    with col2:
        st.subheader("Create Sample & Test Files")
        overwrite_ok = True
        if os.path.exists(INVENTORY_PATH):
            overwrite_ok = st.checkbox(
                f"I understand this will overwrite the existing {INVENTORY_PATH}"
            )
        if st.button("📝 Create Sample Inventory + Test", use_container_width=True, disabled=not overwrite_ok):
            sample_data = {
                'Barcode': ['123456789', '987654321', '555555555', '111111111', '39200'],
                'Name': ['منتج أ', 'منتج ب', 'منتج ج', 'منتج د', 'منتج اختبار'],
                'Qty': [10, 5, 20, 15, 8],
                'Qty_new': [0, 0, 0, 0, 0]
            }
            dff = pd.DataFrame(sample_data)
            with FileLock(LOCK_PATH, timeout=10):
                _atomic_write_csv(dff, 'windows-1256')
            st.session_state['inventory_encoding'] = 'windows-1256'
            st.session_state['inventory_df'] = dff
            st.session_state['inventory_mtime'] = _file_mtime(INVENTORY_PATH)

            tests_dir = 'tests'
            try:
                os.makedirs(tests_dir, exist_ok=True)
                test_content = """
import pandas as pd

def test_inventory_file_exists_and_columns():
    df = pd.read_csv('inventory.csv', encoding='windows-1256')
    cols = [c.lower().replace(' ', '').replace('_', '') for c in df.columns]
    assert 'barcode' in cols
    assert 'name' in cols
    assert any('qty' in c for c in cols)
"""
                with open(os.path.join(tests_dir, 'test_inventory_io.py'), 'w', encoding='utf-8') as f:
                    f.write(test_content)
            except OSError as e:
                st.warning(f"Could not create test file: {e}")

            st.success("Sample inventory.csv and local test file created in runtime (tests/test_inventory_io.py)")
            st.info("This writes files to the app runtime filesystem, not to the Git repo. Use git to commit if you want them in the repo.")


def update_scanned_item_form(session_counter):
    """Form to update one scanned item's quantity manually with confirmation"""
    st.header("✏️ Update Scanned Item Quantity")

    df = load_inventory_df()
    if df is None:
        return

    column_mapping = normalize_column_names(df)
    if 'barcode' not in column_mapping or 'qtynew' not in column_mapping or 'qty' not in column_mapping:
        st.error("inventory.csv must contain barcode, qty and qty_new (or similar) columns to use this form.")
        return

    barcode_col = column_mapping['barcode']
    qty_col = column_mapping['qty']
    qty_new_col = column_mapping['qtynew']
    name_col = column_mapping.get('name')

    st.info("Choose a barcode from scanned session or enter a barcode to update its scanned quantity.")
    session_barcodes = [str(item['barcode']) for item in st.session_state.get('scanned_items', [])]
    inventory_barcodes = df[barcode_col].astype(str).unique().tolist()
    combined = list(dict.fromkeys(session_barcodes + inventory_barcodes))

    col1, col2 = st.columns([2, 1])
    with col1:
        barcode_choice = st.selectbox(
            "Select barcode (or choose 'Enter manually' to type):",
            options=["-- Enter manually --"] + combined
        )
    with col2:
        manual_barcode = st.text_input("Or enter barcode:", key='manual_update_barcode')

    chosen_barcode = None
    if barcode_choice and barcode_choice != "-- Enter manually --":
        chosen_barcode = barcode_choice
    elif manual_barcode:
        chosen_barcode = manual_barcode.strip()

    if chosen_barcode:
        df[barcode_col] = df[barcode_col].astype(str)
        matching = df[df[barcode_col] == chosen_barcode]
        if matching.empty:
            st.error("Barcode not found in inventory.")
        else:
            product = matching.iloc[0]
            st.markdown(f"**Product:** {product.get(name_col, '')}  ")
            try:
                current_qty = int(product.get(qty_col, 0))
            except (ValueError, TypeError):
                current_qty = product.get(qty_col, 0)
            try:
                current_scanned = int(product.get(qty_new_col, 0))
            except (ValueError, TypeError):
                current_scanned = 0
            st.write(f"Current Qty: {current_qty} | Current Scanned: {current_scanned}")

            new_scanned = st.number_input("Set new scanned quantity:", min_value=0, value=int(current_scanned))
            confirm_update = st.checkbox("Confirm update of scanned quantity")

            if st.button("Update Quantity", use_container_width=True, disabled=not confirm_update):
                try:
                    with FileLock(LOCK_PATH, timeout=10):
                        fresh_df, encoding_used = read_csv_with_encoding(INVENTORY_PATH)
                        st.session_state['inventory_encoding'] = encoding_used
                        fresh_df[barcode_col] = fresh_df[barcode_col].astype(str)
                        fresh_df.loc[fresh_df[barcode_col] == chosen_barcode, qty_new_col] = new_scanned
                        saved = _atomic_write_csv(fresh_df, encoding_used)
                except Exception as e:
                    st.error(f"Error updating inventory: {e}")
                    saved = False
                    fresh_df = None

                if saved:
                    st.session_state['inventory_df'] = fresh_df
                    st.session_state['inventory_mtime'] = _file_mtime(INVENTORY_PATH)
                    session_counter.add_item(
                        barcode=chosen_barcode,
                        product_name=product.get(name_col, ''),
                        old_qty=current_scanned,
                        new_qty=new_scanned,
                        action='manual_update'
                    )
                    st.session_state['manual_update_barcode'] = ""  # clear the input field
                    st.success(f"Updated scanned quantity for {chosen_barcode} to {new_scanned}")
                    st.rerun()


def main():
    """Main application"""
    session_counter = SessionCounter()

    with st.sidebar:
        st.title("📦 Barcode Scanner")
        st.markdown("---")

        st.metric("Session Total", session_counter.get_session_total())
        st.markdown("---")

        st.subheader("Navigation")
        page = st.radio(
            "Go to:",
            ["Single Scan", "Continuous Scan", "Session Summary", "Inventory Overview", "Update Scanned Item", "File Management"],
            label_visibility="collapsed"
        )

        st.markdown("---")
        st.markdown("### Quick Actions")
        if st.button("🔄 Reset Current Session", use_container_width=True):
            session_counter.reset_session()
            st.rerun()

        st.markdown("---")
        st.markdown("*Developed with AmR ELSaadAnY*")

    if page == "Single Scan":
        single_scan_mode(session_counter)
    elif page == "Continuous Scan":
        continuous_scan_mode(session_counter)
    elif page == "Session Summary":
        show_session_summary(session_counter)
    elif page == "Inventory Overview":
        inventory_overview()
    elif page == "Update Scanned Item":
        update_scanned_item_form(session_counter)
    elif page == "File Management":
        file_management()


if __name__ == "__main__":
    main()
