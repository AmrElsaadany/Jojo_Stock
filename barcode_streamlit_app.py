# barcode_streamlit_app.py
import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime

# Set page configuration
st.set_page_config(
    page_title="Barcode Scanner Inventory",
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
    """Read CSV file with Arabic (Windows-1256) encoding"""
    # Try a list of encodings; for each encoding try multiple parsing strategies
    encodings = ['windows-1256', 'utf-8', 'cp1256', 'iso-8859-6', 'latin1', 'cp1252']

    for enc in encodings:
        try:
            # First try the default (fast C engine)
            return pd.read_csv(file_path, encoding=enc)
        except UnicodeDecodeError:
            # Encoding didn't match, try next
            continue
        except pd.errors.ParserError as pe:
            # Tokenization/parsing problem (uneven number of fields).
            # Fall back to the python engine which is more forgiving and
            # supports on_bad_lines. Try to read while warning about bad lines.
            try:
                st.warning(f"ParserError with encoding {enc}: {pe}. Retrying with python engine and tolerant parsing.")
                return pd.read_csv(file_path, encoding=enc, engine='python', sep=',', on_bad_lines='warn')
            except Exception:
                # As a final fallback, attempt to reconstruct rows where names
                # contain unquoted commas by joining extra parts into the Name column.
                try:
                    st.warning(f"ParserError with encoding {enc}: attempting row reconstruction.")
                    with open(file_path, 'r', encoding=enc, errors='replace') as f:
                        lines = f.readlines()

                    if not lines:
                        raise Exception('Empty file')

                    header_line = lines[0].rstrip('\n').strip()
                    header_cols = [c.strip() for c in header_line.split(',')]
                    expected = len(header_cols)

                    reconstructed = []
                    repaired = 0

                    for ln in lines[1:]:
                        ln_core = ln.rstrip('\n')
                        parts = ln_core.split(',')

                        if len(parts) == expected:
                            reconstructed.append(parts)
                        elif len(parts) > expected:
                            # Join the middle parts into the 'Name' column
                            # Keep first column as Barcode, last (expected-2) columns as trailing fields
                            num_trailing = expected - 2  # usually 2: Qty and Qty_new
                            if num_trailing < 0:
                                num_trailing = 0

                            barcode = parts[0]
                            if num_trailing > 0:
                                trailing = parts[-num_trailing:]
                                name_parts = parts[1:len(parts)-num_trailing]
                            else:
                                trailing = []
                                name_parts = parts[1:]

                            name = ','.join(name_parts).strip()
                            new_row = [barcode, name] + trailing
                            # pad if still short
                            while len(new_row) < expected:
                                new_row.append('')
                            reconstructed.append(new_row)
                            repaired += 1
                        else:
                            # fewer parts than expected: pad with empty columns
                            new_row = parts + [''] * (expected - len(parts))
                            reconstructed.append(new_row)

                    df = pd.DataFrame(reconstructed, columns=header_cols)
                    st.info(f"Reconstructed CSV with encoding {enc}. Repaired {repaired} lines.")
                    return df
                except Exception as e:
                    # give up for this encoding and try next
                    st.warning(f"Row reconstruction failed for encoding {enc}: {e}")
                    continue
        except Exception:
            # Any other exception for this encoding — try next
            continue

    raise Exception("Could not read the CSV file with any supported encoding or parsing strategy")


def normalize_column_names(df):
    """Normalize column names to handle different cases and spaces"""
    column_mapping = {}
    for col in df.columns:
        normalized = col.lower().replace(' ', '').replace('_', '')
        column_mapping[normalized] = col
    return column_mapping

def update_inventory_data():
    """Load and return inventory data"""
    file_path = "inventory.csv"
    if not os.path.exists(file_path):
        st.error(f"File '{file_path}' not found!")
        return None
    try:
        df = read_csv_with_encoding(file_path)
        return df
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return None

def save_inventory_data(df):
    """Save inventory data back to CSV"""
    try:
        df.to_csv("inventory.csv", index=False, encoding='windows-1256')
        return True
    except Exception as e:
        st.error(f"Error saving file: {e}")
        return False

def single_scan_mode(session_counter):
    """Single barcode scan mode"""
    st.header("📱 Single Scan Mode")

    df = update_inventory_data()
    if df is None:
        return

    # Normalize column names
    column_mapping = normalize_column_names(df)

    # Check required columns
    required_columns = ['barcode', 'name', 'qty', 'qtynew']
    missing_columns = [col for col in required_columns if col not in column_mapping]
    if missing_columns:
        st.error(f"Missing columns: {missing_columns}")
        st.info("Please ensure your CSV has columns for barcode, name, quantity, and new quantity")
        return

    # Get actual column names
    barcode_col = column_mapping['barcode']
    name_col = column_mapping['name']
    qty_col = column_mapping['qty']
    qty_new_col = column_mapping['qtynew']

    # Ensure session_state keys exist
    if 'single_scan_input' not in st.session_state:
        st.session_state.single_scan_input = ""

    # Barcode input
    # If requested, clear the single-scan input BEFORE the widget is created
    if st.session_state.get("clear_single_input", False):
        st.session_state['single_scan_input'] = ""
        st.session_state['clear_single_input'] = False

    col1, col2 = st.columns([2, 1])
    with col1:
        barcode_input = st.text_input("Scan or enter barcode:", key="single_scan_input", placeholder="Scan or type barcode and press Enter...")
    with col2:
        scan_button = st.button("Scan Item", type="primary", use_container_width=True)

    # Accept Enter press in the text_input (Streamlit binds Enter to form submit; here we detect by value)
    if (scan_button or (barcode_input and barcode_input != "" and st.session_state.get('single_scan_processed') != barcode_input)) and barcode_input:
        # avoid double-processing same value
        st.session_state['single_scan_processed'] = barcode_input

        barcode_input = str(barcode_input).strip()
        if not barcode_input:
            st.warning("Please enter or scan a barcode.")
            return

        # Convert barcode column to string for comparison
        df[barcode_col] = df[barcode_col].astype(str)

        # Find matching barcode
        matching_rows = df[df[barcode_col] == barcode_input]

        if matching_rows.empty:
            st.error(f"Barcode '{barcode_input}' not found in database!")
            with st.expander("Show available barcodes"):
                st.write("First 20 barcodes:")
                st.code(", ".join(df[barcode_col].head(20).astype(str).tolist()))
            # clear processed so user can try again
            st.session_state['single_scan_processed'] = ""
        else:
            # Update quantity
            current_value = df.loc[df[barcode_col] == barcode_input, qty_new_col].iloc[0]
            if pd.isna(current_value):
                new_value = 1
            else:
                try:
                    new_value = int(current_value) + 1
                except:
                    new_value = 1

            df.loc[df[barcode_col] == barcode_input, qty_new_col] = new_value

            # Get updated product info
            updated_product = df[df[barcode_col] == barcode_input].iloc[0]

            # Add to session counter
            old_qty_val = updated_product.get(qty_col, 0)
            session_counter.add_item(
                barcode=updated_product[barcode_col],
                product_name=updated_product.get(name_col, ""),
                old_qty=old_qty_val,
                new_qty=new_value
            )

            # Save changes
            if save_inventory_data(df):
                st.success("✅ Item scanned successfully!")

                # Display product info
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Product", updated_product.get(name_col, ""))
                with col2:
                    st.metric("Barcode", updated_product[barcode_col])
                with col3:
                    try:
                        old_q = int(updated_product.get(qty_col, 0))
                    except:
                        old_q = updated_product.get(qty_col, 0)
                    st.metric("Old Quantity", old_q)
                with col4:
                    st.metric("New Quantity", int(new_value))

                st.session_state['clear_single_input'] = True
                st.session_state['single_scan_processed'] = ''
                st.rerun()

def continuous_scan_mode(session_counter):
    """Continuous scan mode"""
    st.header("🔄 Continuous Scan Mode")

    df = update_inventory_data()
    if df is None:
        return

    # Normalize column names
    column_mapping = normalize_column_names(df)
    # Ensure required keys exist
    if any(k not in column_mapping for k in ['barcode', 'name', 'qty', 'qtynew']):
        st.error("inventory.csv must contain barcode, name, qty and qty_new (or similar) columns to use continuous scan.")
        return

    barcode_col = column_mapping['barcode']
    name_col = column_mapping['name']
    qty_col = column_mapping['qty']
    qty_new_col = column_mapping['qtynew']

    # Initialize continuous scan state
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

        # Barcode input for continuous mode
        barcode_input = st.text_input(
            "Scan barcode (press Enter after each scan):",
            key="continuous_scan_input",
            placeholder="Scan barcode and press Enter..."
        )

        # Process the barcode if entered
        if barcode_input and barcode_input.strip():
            barcode_input = barcode_input.strip()

            # Convert barcode column to string
            df[barcode_col] = df[barcode_col].astype(str)

            # Find matching barcode
            matching_rows = df[df[barcode_col] == barcode_input]

            if matching_rows.empty:
                st.error(f"Barcode '{barcode_input}' not found!")
            else:
                # Update quantity
                current_value = df.loc[df[barcode_col] == barcode_input, qty_new_col].iloc[0]
                if pd.isna(current_value):
                    new_value = 1
                else:
                    try:
                        new_value = int(current_value) + 1
                    except:
                        new_value = 1

                df.loc[df[barcode_col] == barcode_input, qty_new_col] = new_value

                # Get updated product info
                updated_product = df[df[barcode_col] == barcode_input].iloc[0]

                # Add to session counter
                session_counter.add_item(
                    barcode=updated_product[barcode_col],
                    product_name=updated_product.get(name_col, ""),
                    old_qty=updated_product.get(qty_col, 0),
                    new_qty=new_value
                )

                # Save changes
                if save_inventory_data(df):
                    st.success(f"✅ Scanned: {updated_product.get(name_col, '')} - New Qty: {new_value}")
                    # Clear the input for the next scan
                    st.session_state['continuous_scan_input'] = ""
                    st.rerun()

def show_session_summary(session_counter):
    """Display session summary"""
    st.header("📊 Session Summary")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Items Scanned", session_counter.get_session_total())
    with col2:
        duration = session_counter.get_session_duration()
        st.metric("Session Duration", f"{duration.seconds // 3600}h {(duration.seconds % 3600) // 60}m")
    with col3:
        if st.button("🔄 Reset Session", use_container_width=True):
            session_counter.reset_session()
            st.success("Session reset successfully!")

    # Display scanned items table
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

        # Export option
        if st.button("📥 Export Session Data"):
            csv = summary_df.to_csv(index=False, encoding='utf-8')
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"scan_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
    else:
        st.info("No items scanned in this session yet.")

def inventory_overview():
    """Display inventory overview"""
    st.header("📦 Inventory Overview")

    df = update_inventory_data()
    if df is None:
        return

    # Normalize column names
    column_mapping = normalize_column_names(df)

    # Check if we have the required columns
    if 'qtynew' in column_mapping:
        qty_new_col = column_mapping['qtynew']
        name_col = column_mapping.get('name', None)
        barcode_col = column_mapping.get('barcode', None)

        # Display statistics
        total_scanned = df[qty_new_col].sum() if not df[qty_new_col].isna().all() else 0
        unique_items_scanned = df[df[qty_new_col] > 0].shape[0] if not df[qty_new_col].isna().all() else 0

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Products", len(df))
        with col2:
            st.metric("Total Items Scanned", int(total_scanned))
        with col3:
            st.metric("Unique Items Scanned", unique_items_scanned)

        # Show items that have been scanned
        scanned_items = df[df[qty_new_col] > 0] if not df[qty_new_col].isna().all() else pd.DataFrame()
        if not scanned_items.empty:
            st.subheader("✅ Scanned Items in Inventory")
            display_df = scanned_items[[barcode_col, name_col, qty_new_col]].copy()
            display_df.columns = ['Barcode', 'Product Name', 'Scanned Quantity']
            st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Show all inventory with search
        st.subheader("🔍 Full Inventory")
        search_term = st.text_input("Search products:", placeholder="Enter product name or barcode...")

        display_full_df = df.copy()
        if search_term:
            mask = (
                display_full_df[name_col].astype(str).str.contains(search_term, case=False, na=False) |
                display_full_df[barcode_col].astype(str).str.contains(search_term, case=False, na=False)
            )
            display_full_df = display_full_df[mask]

        # Select columns to display
        display_columns = [barcode_col, name_col]
        if 'qty' in column_mapping:
            display_columns.append(column_mapping['qty'])
        if 'qtynew' in column_mapping:
            display_columns.append(column_mapping['qtynew'])

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
            file_path = "inventory.csv"
            if os.path.exists(file_path):
                try:
                    df = pd.read_csv(file_path)
                    df.to_csv(file_path, index=False, encoding='windows-1256')
                    st.success("File encoding fixed to Windows-1256 (Arabic)")
                except Exception as e:
                    st.error(f"Error fixing encoding: {e}")
            else:
                st.error("inventory.csv not found!")

    with col2:
        st.subheader("Create Sample & Test Files")
        if st.button("📝 Create Sample Inventory + Test", use_container_width=True):
            # Create sample inventory
            sample_data = {
                'Barcode': ['123456789', '987654321', '555555555', '111111111', '39200'],
                'Name': ['منتج أ', 'منتج ب', 'منتج ج', 'منتج د', 'منتج اختبار'],
                'Qty': [10, 5, 20, 15, 8],
                'Qty_new': [0, 0, 0, 0, 0]
            }
            dff = pd.DataFrame(sample_data)
            dff.to_csv('inventory.csv', index=False, encoding='windows-1256')

            # Create a basic local pytest test file to help testing (saved to runtime FS)
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
            except Exception as e:
                st.warning(f"Could not create test file: {e}")

            st.success("Sample inventory.csv and local test file created in runtime (tests/test_inventory_io.py)")
            st.info("This writes files to the app runtime filesystem, not to the Git repo. Use git to commit if you want them in the repo.")

def update_scanned_item_form(session_counter):
    """Form to update one scanned item's quantity manually with confirmation modal"""
    st.header("✏️ Update Scanned Item Quantity")

    df = update_inventory_data()
    if df is None:
        return

    column_mapping = normalize_column_names(df)
    # Validate necessary columns
    if 'barcode' not in column_mapping or 'qtynew' not in column_mapping or 'qty' not in column_mapping:
        st.error("inventory.csv must contain barcode, qty and qty_new (or similar) columns to use this form.")
        return

    barcode_col = column_mapping['barcode']
    qty_col = column_mapping['qty']
    qty_new_col = column_mapping['qtynew']
    name_col = column_mapping.get('name', None)

    st.info("Choose a barcode from scanned session or enter a barcode to update its scanned quantity.")
    # Prepare options from session scanned items + inventory
    session_barcodes = [str(item['barcode']) for item in st.session_state.get('scanned_items', [])]
    inventory_barcodes = df[barcode_col].astype(str).unique().tolist()
    combined = list(dict.fromkeys(session_barcodes + inventory_barcodes))

    col1, col2 = st.columns([2, 1])
    with col1:
        # selectbox supports typing to search; if you prefer a different widget, change here
        barcode_choice = st.selectbox("Select barcode (or choose 'Enter manually' to type):", options=["-- Enter manually --"] + combined)
    with col2:
        manual_barcode = st.text_input("Or enter barcode:", key='manual_update_barcode', value="" if st.session_state.get("clear_manual_barcode", False) else None)

    if st.session_state.get("clear_manual_barcode", False):
        st.session_state['clear_manual_barcode'] = False

    chosen_barcode = None
    if barcode_choice and barcode_choice != "-- Enter manually --":
        chosen_barcode = barcode_choice
    elif manual_barcode:
        chosen_barcode = manual_barcode.strip()

    if chosen_barcode:
        # find product in inventory
        df[barcode_col] = df[barcode_col].astype(str)
        matching = df[df[barcode_col] == chosen_barcode]
        if matching.empty:
            st.error("Barcode not found in inventory.")
        else:
            product = matching.iloc[0]
            st.markdown(f"**Product:** {product.get(name_col, '')}  ")
            try:
                current_qty = int(product.get(qty_col, 0))
            except:
                current_qty = product.get(qty_col, 0)
            try:
                current_scanned = int(product.get(qty_new_col, 0))
            except:
                current_scanned = product.get(qty_new_col, 0)
            st.write(f"Current Qty: {current_qty} | Current Scanned: {current_scanned}")

            new_scanned = st.number_input("Set new scanned quantity:", min_value=0, value=int(current_scanned) if str(current_scanned).isdigit() else 0)

            confirm_update = st.checkbox("Confirm update of scanned quantity")

            if st.button("Update Quantity", use_container_width=True, disabled=not confirm_update):
                df.loc[df[barcode_col] == chosen_barcode, qty_new_col] = new_scanned
                if save_inventory_data(df):
                    session_counter.add_item(
                        barcode=chosen_barcode,
                        product_name=product.get(name_col, ''),
                        old_qty=current_scanned,
                        new_qty=new_scanned,
                        action='manual_update'
                    )
                    st.success(f"Updated scanned quantity for {chosen_barcode} to {new_scanned}")
                    # Clear manual input field
                    st.session_state['clear_manual_barcode'] = True
                    st.rerun()

def main():
    """Main application"""
    # Initialize session counter
    session_counter = SessionCounter()

    # Sidebar
    with st.sidebar:
        st.title("📦 Barcode Scanner")
        st.markdown("---")

        # Session info
        st.metric("Session Total", session_counter.get_session_total())
        st.markdown("---")

        # Navigation
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
        st.markdown("*Developed with Streamlit*")

    # Main content based on navigation
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