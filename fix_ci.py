def replace_in_file(filepath, search_text, replace_text):
    with open(filepath, 'r') as f:
        content = f.read()
    if search_text in content:
        content = content.replace(search_text, replace_text)
        with open(filepath, 'w') as f:
            f.write(content)

replace_in_file(".github/workflows/review.yml",
                "ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}",
                "ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}")
