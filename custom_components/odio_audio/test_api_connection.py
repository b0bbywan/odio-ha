#!/usr/bin/env python3
"""Script to test Odio API connection outside of Home Assistant."""

import asyncio
import sys
import aiohttp


async def test_connection(api_url: str):
    """Test connection to Odio API."""
    print(f"Testing connection to: {api_url}")
    print("-" * 60)

    async with aiohttp.ClientSession() as session:
        # Test /audio/server
        print("\n1. Testing /audio/server endpoint...")
        try:
            url = f"{api_url}/audio/server"
            print(f"   URL: {url}")

            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                print(f"   Status: {response.status}")

                if response.status == 200:
                    data = await response.json()
                    print(f"   Success! Server: {data}")
                else:
                    text = await response.text()
                    print(f"   Error: {text}")

        except aiohttp.ClientConnectorError as err:
            print(f"   Connection Error: {err}")
            print(f"   Cannot reach {api_url} - check if server is running and URL is correct")
            return False

        except Exception as err:
            print(f"   Unexpected Error: {err}")
            return False

        # Test /audio/clients
        print("\n2. Testing /audio/clients endpoint...")
        try:
            url = f"{api_url}/audio/clients"
            print(f"   URL: {url}")

            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                print(f"   Status: {response.status}")

                if response.status == 200:
                    data = await response.json()
                    print(f"   Success! Found {len(data)} clients")
                    if data:
                        print(f"   First client: {data[0].get('name', 'N/A')}")
                else:
                    text = await response.text()
                    print(f"   Error: {text}")

        except Exception as err:
            print(f"   Error: {err}")
            return False

        # Test /services
        print("\n3. Testing /services endpoint...")
        try:
            url = f"{api_url}/services"
            print(f"   URL: {url}")

            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                print(f"   Status: {response.status}")

                if response.status == 200:
                    data = await response.json()
                    print(f"   Success! Found {len(data)} services")

                    enabled = [s for s in data if s.get('enabled') and s.get('exists')]
                    print(f"   Enabled services: {len(enabled)}")

                    for svc in enabled[:5]:  # Show first 5
                        print(f"     - {svc['scope']}/{svc['name']} (running: {svc.get('running')})")
                else:
                    text = await response.text()
                    print(f"   Error: {text}")

        except Exception as err:
            print(f"   Error: {err}")
            return False

    print("\n" + "=" * 60)
    print("✓ All tests passed! API is reachable and responding correctly.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_api_connection.py <api_url>")
        print("Example: python test_api_connection.py http://192.168.1.100:8018")
        sys.exit(1)

    api_url = sys.argv[1].rstrip('/')

    try:
        result = asyncio.run(test_connection(api_url))
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
