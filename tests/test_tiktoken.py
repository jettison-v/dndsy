import tiktoken

def test_encodings():
    # Test different encodings
    encodings = ["cl100k_base", "p50k_base", "r50k_base"]
    test_string = "Hello, this is a test of tiktoken with D&D content: A dragon's breath weapon deals 2d6 fire damage!"
    
    print("Testing tiktoken encodings:\n")
    
    for encoding_name in encodings:
        try:
            # Get the encoding
            encoding = tiktoken.get_encoding(encoding_name)
            
            # Encode the text
            encoded = encoding.encode(test_string)
            
            # Decode back to text
            decoded = encoding.decode(encoded)
            
            print(f"\nEncoding: {encoding_name}")
            print(f"Original text: {test_string}")
            print(f"Token count: {len(encoded)}")
            print(f"Encoded (first 10 tokens): {encoded[:10]}")
            print(f"Decoded text matches original: {test_string == decoded}")
            print("-" * 80)
            
        except Exception as e:
            print(f"Error with {encoding_name}: {str(e)}")

if __name__ == "__main__":
    print("Starting tiktoken test...")
    test_encodings() 