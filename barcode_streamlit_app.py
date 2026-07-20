import streamlit as st
import pandas as pd
import os
import shutil
import tempfile
import threading
from datetime import datetime

try:
    from filelock import FileLock as RealFileLock
except ImportError:
    RealFileLock = None

# Fallback lock if the `filelock` package isn't installed.
class Timeout(Exception):
    pass

class FallbackFileLock:
    _locks_by_path = {}
    _registry_guard = threading.Lock()

    def __init__(self, path, timeout=10):
        self.path = path
        self.timeout = timeout
        with FallbackFileLock._registry_guard:
            if path not in FallbackFileLock._locks_by_path:
                FallbackFileLock._locks_by_path[path] = threading.Lock()
            self._lock = FallbackFileLock._locks_by_path[path]

    def __enter__(self):
        acquired = self._lock.acquire(timeout=self.timeout)
        if not acquired:
            raise Timeout(f"Could not acquire lock on {self.path} within {self.timeout}s")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()
        return False

# Use real filelock if available, otherwise fallback
FileLock = RealFileLock if RealFileLock else FallbackFileLock

INVENTORY_PATH = "inventory.csv"
LOCK_PATH = "inventory.csv.lock"
BACKUP_PATH = "inventory.csv.bak"
SESSION_BACKUP_DIR = "session_backups"
SESSION_BACKUP_LOCK = "session_backup.lock"

# Set page configuration
st.set_page_config(
    page_title="Barcode Scanner Inventory",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

class SessionCounter:
    """Class to track session statistics and keep a live backup CSV of
    just this session's scanned/updated items."""
    def __init__(self):
        if 'session_total' not in st.session_state:
            st.session_state.session_total = 0
        if 'scanned_items' not in st.session_state:
            st.session_state.scanned_items = []
        if 'session_start_time' not in st.session_state:
            st.session_state.session_start_time = datetime.now()
        if 'session_backup_path' not in st.session_state:
            os.makedirs(SESSION_BACKUP_DIR, exist_ok=True)
            stamp = st.session_state.session_start_time.strftime("%Y%m%d_%H%M%S")
            st.session_state.session_backup_path = os.path.join(
                SESSION_BACKUP_DIR, f"session_{stamp}.csv"
            )

    def add_item(self, barcode, product_name, old_qty, new_qty, action='scan'):
        st.session_state.session_total += 1
        st.session_state.scanned_items.append({
            'barcode': barcode,
            'product_name': product_name,
            'old_qty': old_qty,
            'new_qty': new_qty,
            'action': action,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        self._save_session_backup()

    def _save_session_backup(self):
        if not st.session_state.scanned_items:
            return
        try:
            df = pd.DataFrame(st.session_state.scanned_items)
            path = st.session_state.session_backup_path
            dir_name = os.path.dirname(os.path.abspath(path)) or "."
            with FileLock(SESSION_BACKUP_LOCK, timeout=10):
                fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".csv.tmp")
                os.close(fd)
                df.to_csv(tmp_path, index=False, encoding='utf-8-sig')
                os.replace(tmp_path, path)
        except Exception as e:
            st.warning(f"Could not write session backup: {e}")

    def get_session_total(self):
        return st.session_state.session_total

    def get_session_duration(self):
        return datetime.now() - st.session_state.session_start_time

    def get_backup_path(self):
        return st.session_state.get('session_backup_path')

    def reset_session(self):
        st.session_state.session_total = 0
        st.session_state.scanned_items = []
        st.session_state.session_start_time = datetime.now()
        os.makedirs(SESSION_BACKUP_DIR, exist_ok=True)
        stamp = st.session_state.session_start_time.strftime("%Y%m%d_%H%M%S")
        st.session_state.session_backup_path = os.path.join(
            SESSION_BACKUP_DIR, f"session_{stamp}.csv"
        )

def read_csv_with_encoding(file_path):
    """Read CSV file, prioritizing UTF-8, with fallback to Arabic (Windows-1256)."""
    encodings = ['utf-8-sig', 'utf-8', 'windows-1256', 'cp1256', 'iso-8859-6', 'latin1']
    for enc in encodings:
        try:
            df = pd.read_csv(file_path, encoding=enc)
            return df, enc
        except UnicodeDecodeError:
            continue
        except pd.errors.ParserError as pe:
            try:
                df = pd.read_csv(file_path, encoding=enc, engine='python', on_bad_lines='warn')
                return df, enc
            except Exception:
                pass
    
    raise Exception("Could not read the CSV file with any supported encoding.")

def standardize_columns(df):
    """Standardize column names to a canonical format to prevent case-sensitivity conflicts 
    (e.g., 'barcode' vs 'Barcode' vs 'BARCODE')."""
    canonical_mapping = {
        'barcode': 'Barcode',
        'name': 'Name',
        'qty': 'Qty',
        'quantity': 'Qty',
        'qtynew': 'Qty_new',
        'newqty': 'Qty_new',
        'qty_new': 'Qty_new',
        'new_quantity': 'Qty_new'
    }
    
    new_columns = []
    for col in df.columns:
        cleaned = str(col).lower().replace(' ', '').replace('_', '')
        if cleaned in canonical_mapping:
            new_columns.append(canonical_mapping[cleaned])
        else:
            new_columns.append(str(col))
    
    df.columns = new_columns
    return df

def _file_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None

def load_inventory_df(force_reload=False):
    """Load inventory.csv, cached in session_state."""
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
        df = standardize_columns(df) # Enforce canonical column names
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return None
    
    st.session_state['inventory_df'] = df
    st.session_state['inventory_mtime'] = current_mtime
    st.session_state['inventory_encoding'] = encoding_used
    return df.copy()

def _atomic_write_csv(df, encoding):
    """Write df to INVENTORY_PATH atomically, with a rotating backup."""
    if os.path.exists(INVENTORY_PATH):
        try:
            shutil.copyfile(INVENTORY_PATH, BACKUP_PATH)
        except OSError as e:
            st.warning(f"Could not create backup before saving: {e}")
    
    dir_name = os.path.dirname(os.path.abspath(INVENTORY_PATH)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".csv.tmp")
    os.close(fd)
    
    try:
        # Always save as utf-8-sig for maximum compatibility with Excel and GitHub
        df.to_csv(tmp_path, index=False, encoding='utf-8-sig')
    except UnicodeEncodeError as e:
        os.remove(tmp_path)
        st.error(f"Could not encode data: {e}. Consider cleaning special characters.")
        return False
        
    os.replace(tmp_path, INVENTORY_PATH)
    return True

def save_inventory_data(df):
    """Acquire the lock and atomically save inventory data."""
    try:
        with FileLock(LOCK_PATH, timeout=10):
            ok = _atomic_write_csv(df, 'utf-8-sig')
            if ok:
                st.session_state['inventory_df'] = df
                st.session_state['inventory_mtime'] = _file_mtime(INVENTORY_PATH)
            return ok
    except Exception as e:
        st.error(f"Error saving file: {e}")
        return False

def scan_barcode(qty_col, qty_new_col, name_col, barcode_input, session_counter, action='scan'):
    """Increment the scanned quantity for barcode_input as a single locked transaction."""
    try:
        with FileLock(LOCK_PATH, timeout=10):
            try:
                df, encoding_used = read_csv_with_encoding(INVENTORY_PATH)
                df = standardize_columns(df)
            except Exception as e:
                st.error(f"Error reading file: {e}")
                return None
            
            st.session_state['inventory_encoding'] = encoding_used
            df['Barcode'] = df['Barcode'].astype(str).str.strip()
            matching_rows = df[df['Barcode'] == str(barcode_input).strip()]
            
            if matching_rows.empty:
                return "not_found"
            
            current_value = df.loc[df['Barcode'] == str(barcode_input).strip(), qty_new_col].iloc[0]
            if pd.isna(current_value):
                new_value = 1
            else:
                try:
                    new_value = int(float(current_value)) + 1
                except (ValueError, TypeError):
                    new_value = 1
                    
            df.loc[df['Barcode'] == str(barcode_input).strip(), qty_new_col] = new_value
            updated_product = df[df['Barcode'] == str(barcode_input).strip()].iloc[0].copy()
            
            if not _atomic_write_csv(df, 'utf-8-sig'):
                return None
                
            st.session_state['inventory_df'] = df
            st.session_state['inventory_mtime'] = _file_mtime(INVENTORY_PATH)
            
        session_counter.add_item(
            barcode=updated_product['Barcode'],
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
    st.header("📱 Single Scan Mode")
    df = load_inventory_df()
    if df is None:
        return
    
    required_columns = ['Barcode', 'Name', 'Qty', 'Qty_new']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        st.error(f"Missing columns after standardization: {missing_columns}")
        return

    with st.form("single_scan_form", clear_on_submit=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            barcode_input = st.text_input("Scan or enter barcode:", placeholder="Scan or type barcode and press Enter...")
        with col2:
            st.write("")
            submitted = st.form_submit_button("Scan Item", type="primary", use_container_width=True)

    if submitted:
        barcode_input = str(barcode_input or "").strip()
        if not barcode_input:
            st.warning("Please enter or scan a barcode.")
            return
        
        result = scan_barcode('Qty', 'Qty_new', 'Name', barcode_input, session_counter)
        if result == "not_found":
            st.error(f"Barcode '{barcode_input}' not found in database!")
        elif result is not None:
            updated_product, new_value = result
            st.success("✅ Item scanned successfully!")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Product", updated_product.get('Name', ""))
            col2.metric("Barcode", updated_product['Barcode'])
            col3.metric("Old Scanned Qty", int(updated_product.get('Qty_new', 0)))
            col4.metric("New Scanned Qty", int(new_value))

def continuous_scan_mode(session_counter):
    st.header("🔄 Continuous Scan Mode")
    df = load_inventory_df()
    if df is None:
        return
    
    if 'continuous_scan_active' not in st.session_state:
        st.session_state.continuous_scan_active = False

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("🎯 Start Continuous Scan", type="primary", use_container_width=True):
            st.session_state.continuous_scan_active = True
        if st.button("🛑 Stop Continuous Scan", use_container_width=True):
            st.session_state.continuous_scan_active = False

    if st.session_state.continuous_scan_active:
        st.info("💡 Scan barcodes in the input field below. Press Enter after each scan.")
        with st.form("continuous_scan_form", clear_on_submit=True):
            barcode_input = st.text_input("Scan barcode (press Enter after each scan):", placeholder="Scan barcode...")
            submitted = st.form_submit_button("Add Scan", use_container_width=True)
            
        if submitted:
            barcode_input = str(barcode_input or "").strip()
            if barcode_input:
                result = scan_barcode('Qty', 'Qty_new', 'Name', barcode_input, session_counter)
                if result == "not_found":
                    st.error(f"Barcode '{barcode_input}' not found!")
                elif result is not None:
                    updated_product, new_value = result
                    st.success(f"✅ Scanned: {updated_product.get('Name', '')} - New Qty: {new_value}")

def show_session_summary(session_counter):
    st.header("📊 Session Summary")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Items Scanned", session_counter.get_session_total())
    with col2:
        duration = session_counter.get_session_duration()
        total_seconds = int(duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        st.metric("Session Duration", f"{hours}h {minutes}m")
    with col3:
        if st.button("🔄 Reset Session", use_container_width=True):
            session_counter.reset_session()
            st.rerun()

    if st.session_state.scanned_items:
        summary_df = pd.DataFrame(st.session_state.scanned_items)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
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
    st.header("📦 Inventory Overview")
    df = load_inventory_df()
    if df is None:
        return

    qty_new_numeric = pd.to_numeric(df['Qty_new'], errors='coerce').fillna(0)
    total_scanned = int(qty_new_numeric.sum())
    unique_items_scanned = int((qty_new_numeric > 0).sum())

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Products", len(df))
    col2.metric("Total Items Scanned", total_scanned)
    col3.metric("Unique Items Scanned", unique_items_scanned)

    scanned_items = df[qty_new_numeric > 0]
    if not scanned_items.empty:
        st.subheader("✅ Scanned Items in Inventory")
        display_df = scanned_items[['Barcode', 'Name', 'Qty_new']].copy()
        display_df.columns = ['Barcode', 'Product Name', 'Scanned Quantity']
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.subheader("🔍 Full Inventory")
    search_term = st.text_input("Search products:", placeholder="Enter product name or barcode...")
    display_full_df = df.copy()
    
    if search_term:
        mask = (
            display_full_df['Name'].astype(str).str.contains(search_term, case=False, na=False, regex=False) |
            display_full_df['Barcode'].astype(str).str.contains(search_term, case=False, na=False, regex=False)
        )
        display_full_df = display_full_df[mask]

    st.dataframe(display_full_df[['Barcode', 'Name', 'Qty', 'Qty_new']], use_container_width=True, hide_index=True, height=400)

def file_management(session_counter):
    st.header("⚙️ File Management & GitHub Sync")
    st.warning("⚠️ **Streamlit Cloud Limitation**: This app runs on an ephemeral filesystem. Changes saved here **will not** automatically update your GitHub repository. Use the download button below to save the updated CSV, then manually commit it to GitHub.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Download Updated Inventory")
        if os.path.exists(INVENTORY_PATH):
            df = load_inventory_df()
            if df is not None:
                csv = df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 Download inventory.csv for GitHub",
                    data=csv,
                    file_name="inventory.csv",
                    mime="text/csv",
                    use_container_width=True
                )
        else:
            st.error(f"{INVENTORY_PATH} not found!")

    with col2:
        st.subheader("Create Sample Inventory")
        overwrite_ok = True
        if os.path.exists(INVENTORY_PATH):
            overwrite_ok = st.checkbox("I understand this will overwrite the existing local inventory.csv")
            
        if st.button("📝 Create Sample Inventory", use_container_width=True, disabled=not overwrite_ok):
            sample_data = {
                'Barcode': ['123456789', '987654321', '555555555', '111111111', '39200'],
                'Name': ['منتج أ', 'منتج ب', 'منتج ج', 'منتج د', 'منتج اختبار'],
                'Qty': [10, 5, 20, 15, 8],
                'Qty_new': [0, 0, 0, 0, 0]
            }
            dff = pd.DataFrame(sample_data)
            with FileLock(LOCK_PATH, timeout=10):
                _atomic_write_csv(dff, 'utf-8-sig')
            st.session_state['inventory_df'] = dff
            st.session_state['inventory_mtime'] = _file_mtime(INVENTORY_PATH)
            st.success("Sample inventory.csv created locally. Download it to push to GitHub!")

def update_scanned_item_form(session_counter):
    st.header("✏️ Update Scanned Item Quantity")
    df = load_inventory_df()
    if df is None:
        return

    st.info("Choose a barcode from scanned session or enter a barcode to update its scanned quantity.")
    session_barcodes = [str(item['barcode']) for item in st.session_state.get('scanned_items', [])]
    inventory_barcodes = df['Barcode'].astype(str).unique().tolist()
    combined = list(dict.fromkeys(session_barcodes + inventory_barcodes))

    if 'manual_barcode_widget_version' not in st.session_state:
        st.session_state.manual_barcode_widget_version = 0
    manual_input_key = f"manual_update_barcode_{st.session_state.manual_barcode_widget_version}"

    col1, col2 = st.columns([2, 1])
    with col1:
        barcode_choice = st.selectbox("Select barcode (or choose 'Enter manually' to type):", options=["-- Enter manually --"] + combined)
    with col2:
        manual_barcode = st.text_input("Or enter barcode:", key=manual_input_key)

    chosen_barcode = None
    if barcode_choice and barcode_choice != "-- Enter manually --":
        chosen_barcode = barcode_choice
    elif manual_barcode:
        chosen_barcode = manual_barcode.strip()

    if chosen_barcode:
        df['Barcode'] = df['Barcode'].astype(str).str.strip()
        matching = df[df['Barcode'] == str(chosen_barcode).strip()]
        if matching.empty:
            st.error("Barcode not found in inventory.")
        else:
            product = matching.iloc[0]
            st.markdown(f"**Product:** {product.get('Name', '')}")
            current_scanned = int(float(product.get('Qty_new', 0))) if pd.notna(product.get('Qty_new', 0)) else 0
            st.write(f"Current Scanned Qty: {current_scanned}")
            
            new_scanned = st.number_input("Set new scanned quantity:", min_value=0, value=current_scanned)
            confirm_update = st.checkbox("Confirm update of scanned quantity")
            
            if st.button("Update Quantity", use_container_width=True, disabled=not confirm_update):
                try:
                    with FileLock(LOCK_PATH, timeout=10):
                        fresh_df, encoding_used = read_csv_with_encoding(INVENTORY_PATH)
                        fresh_df = standardize_columns(fresh_df)
                        fresh_df['Barcode'] = fresh_df['Barcode'].astype(str).str.strip()
                        fresh_df.loc[fresh_df['Barcode'] == str(chosen_barcode).strip(), 'Qty_new'] = new_scanned
                        saved = _atomic_write_csv(fresh_df, 'utf-8-sig')
                except Exception as e:
                    st.error(f"Error updating inventory: {e}")
                    saved = False
                    fresh_df = None
                    
                if saved:
                    st.session_state['inventory_df'] = fresh_df
                    st.session_state['inventory_mtime'] = _file_mtime(INVENTORY_PATH)
                    session_counter.add_item(
                        barcode=chosen_barcode,
                        product_name=product.get('Name', ''),
                        old_qty=current_scanned,
                        new_qty=new_scanned,
                        action='manual_update'
                    )
                    st.session_state.manual_barcode_widget_version += 1
                    st.success(f"Updated scanned quantity for {chosen_barcode} to {new_scanned}")
                    st.rerun()

def main():
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
        file_management(session_counter)

if __name__ == "__main__":
    main()

