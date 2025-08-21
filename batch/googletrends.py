from playwright.sync_api import sync_playwright
import json
import time


def capture_google_trends_data(query, geo, hl, date):
    """
    Capture Google Trends data for a given query and geographic location.

    Args:
        query (str): The search term to query on Google Trends.
        geo (str): The geographic location (e.g., "US" for the United States).
        hl (str): The language for the Google Trends interface (default is "en-US").

    Returns:
        dict: A dictionary containing captured data from Google Trends endpoints.
    """
    with sync_playwright() as playwright:
        # Launch browser in headless mode
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Dictionary to store captured data
        captured_data = {}

        def handle_response(response):
            """
            Handle and process responses from Google Trends API endpoints.
            """
            url = response.url

            # Check if the response is from a relevant Google Trends API endpoint
            if (
                "trends/api/widgetdata/multiline" in url
                or "trends/api/widgetdata/comparedgeo" in url
            ):
                try:
                    response_text = response.text()
                    print(response_text)

                    # Skip empty responses
                    if not response_text:
                        return

                    # Clean up Google's special JSON format
                    if response_text.startswith(")]}'"):
                        response_text = response_text[4:].lstrip(",")

                    # Parse JSON data
                    data = json.loads(response_text)

                    # Determine the type of endpoint
                    endpoint_type = (
                        "interest_over_time"
                        if "multiline" in url
                        else "interest_by_region"
                    )

                    # Store the data
                    captured_data[endpoint_type] = data

                    # Save the data to a file
                    filename = f"google_trends_{query}_{endpoint_type}.json"
                    with open(filename, "w") as file:
                        json.dump(data, file, indent=2)
                    print(f"Saved {endpoint_type} data to {filename}")

                except Exception as e:
                    print(f"Error processing response: {e}")

        # Listen for responses
        page.on("response", handle_response)

        # Construct the Google Trends URL
        trends_url = (
            f"https://trends.google.com/trends/explore?date={date}&geo={geo}&q={query}&hl={hl}"
        )
        print(f"Opening Google Trends for '{query}' in {geo}...")
        print(f"▶ Opening: {trends_url}")

        # Navigate to the Google Trends page and wait for it to load
        page.goto(trends_url, wait_until="networkidle")

        # Wait to ensure all requests are completed
        time.sleep(8)

        # Scroll to trigger additional requests
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)

        # If no data was captured, try refreshing the page
        if not captured_data:
            print("No data captured. Refreshing page...")
            page.reload(wait_until="networkidle")
            time.sleep(8)

        # Close the browser
        browser.close()

        # Return the results
        if captured_data:
            print(f"Successfully captured data from {len(captured_data)} endpoints.")
        else:
            print("No Google Trends data was captured.")

        return captured_data


if __name__ == "__main__":
    # Example usage
    query = "Galaxy Z Fold 7, Galaxy Z Fold 6, Galaxy Z Fold 5, Galaxy Z Fold 4, Galaxy Z Fold 3"
    geo = ""
    hl="KR"
    date="2020-01-01 2025-07-18"

    data = capture_google_trends_data(query, geo, hl, date)
