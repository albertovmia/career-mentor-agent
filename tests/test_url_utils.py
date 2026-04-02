from utils.url_utils import normalize_url

def test_normalization():
    tests = [
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "youtube.com/watch?v=dqw4w9wgxcq"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&utm_source=test", "youtube.com/watch?v=dqw4w9wgxcq"),
        ("http://www.google.com/", "google.com"),
        ("https://medium.com/@user/post-title/", "medium.com/@user/post-title"),
    ]
    
    for input_url, expected in tests:
        result = normalize_url(input_url)
        print(f"Input: {input_url}")
        print(f"Result: {result}")
        print(f"Expected: {expected}")
        assert result == expected, f"Failed: {input_url} -> {result} != {expected}"
        print("PASS")

if __name__ == "__main__":
    test_normalization()
