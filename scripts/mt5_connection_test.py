import MetaTrader5 as mt5


def main():
    print("=" * 50)
    print("AI EA LAB - MT5 CONNECTION TEST")
    print("=" * 50)

    if not mt5.initialize():
        print("❌ Failed to initialize MetaTrader 5")
        print(f"Error: {mt5.last_error()}")
        return

    print("✅ MT5 connection successful!")
    print()

    terminal = mt5.terminal_info()
    account = mt5.account_info()

    if terminal:
        print(f"Terminal: {terminal.name}")
        print(f"Build: {terminal.build}")

    if account:
        print(f"Account: {account.login}")
        print(f"Server: {account.server}")
        print(f"Balance: {account.balance}")

    mt5.shutdown()

    print()
    print("✅ Connection test completed.")


if __name__ == "__main__":
    main()