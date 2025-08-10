# Nama file: charyb_fault.py
import sys
import os
import errno

# --- INI BAGIAN UTAMA PERBAIKAN ---
# Kita menggunakan path absolut yang pasti benar, tidak peduli dari mana skrip dijalankan.
# os.path.expanduser('~') akan secara otomatis diganti dengan /home/cc (atau home dir Anda)
CHARYBDEFS_GEN_PY_PATH = os.path.expanduser('~/charybdefs/gen-py')

# Periksa apakah path tersebut ada
if not os.path.isdir(CHARYBDEFS_GEN_PY_PATH):
    print(f"FATAL: Direktori library CharybdeFS tidak ditemukan di: {CHARYBDEFS_GEN_PY_PATH}")
    print("Pastikan Anda sudah menjalankan 'thrift -r --gen py server.thrift' di dalam direktori 'charybdefs'.")
    sys.exit(1)

# Tambahkan path ini ke daftar pencarian modul Python
if CHARYBDEFS_GEN_PY_PATH not in sys.path:
    sys.path.insert(0, CHARYBDEFS_GEN_PY_PATH)

# Sekarang, kita coba import
try:
    from thrift.transport import TSocket, TTransport
    from thrift.protocol import TBinaryProtocol
    from server import server
except ImportError as e:
    print(f"FATAL: Gagal mengimpor library yang dibutuhkan. Error: {e}")
    print(f"Path yang digunakan: {CHARYBDEFS_GEN_PY_PATH}")
    sys.exit(1)


def connect_client():
    try:
        transport = TSocket.TSocket('127.0.0.1', 9090)
        transport = TTransport.TBufferedTransport(transport)
        protocol = TBinaryProtocol.TBinaryProtocol(transport)
        client = server.Client(protocol)
        transport.open()
        return client, transport
    except TTransport.TException as e:
        print(f"Error: Tidak bisa terhubung ke charybdefs di port 9090. Pastikan charybdefs sudah berjalan.")
        print(f"Detail: {e}")
        sys.exit(1)

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ['--delay', '--sync-delay', '--clear']:
        print("Usage: python3 charyb_fault.py --delay <us> | --sync-delay <us> | --clear")
        sys.exit(1)

    client, transport = connect_client()
    command = sys.argv[1]

    try:
        if command == '--clear':
            print("[FAULT INJECTOR] Menghapus semua fault...")
            client.clear_all_faults()
            print("[FAULT INJECTOR] Fault berhasil dihapus.")

        elif command == '--delay' or command == '--sync-delay':
            if len(sys.argv) != 3:
                print(f"Error: Argumen delay_microseconds dibutuhkan untuk {command}.")
                sys.exit(1)

            delay_us = int(sys.argv[2])

            if command == '--sync-delay':
                methods_to_fault = ['fsync', 'fdatasync', 'fsyncdir']
                print(f"[FAULT INJECTOR] Menginjeksi delay {delay_us}us HANYA pada: {methods_to_fault}")
                client.set_fault(methods_to_fault, False, 0, 100000, "", False, delay_us, False)
            else: # --delay
                print(f"[FAULT INJECTOR] Menginjeksi delay {delay_us}us pada SEMUA syscall...")
                client.set_all_fault(False, 0, 100000, "", False, delay_us, False)

            print(f"[FAULT INJECTOR] Injeksi fault berhasil.")

    except Exception as e:
        print(f"Terjadi error saat berkomunikasi dengan charybdefs: {e}")
    finally:
        transport.close()

if __name__ == "__main__":
    main()