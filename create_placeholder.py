#!/usr/bin/env python3
"""
Run this once to create the placeholder image:
    python create_placeholder.py
"""
svg = """<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
  <rect width="600" height="400" fill="#F0F4FF"/>
  <rect x="160" y="140" width="280" height="120" rx="20" fill="#D6E0F5"/>
  <rect x="200" y="120" width="200" height="60" rx="10" fill="#B8C8EE"/>
  <circle cx="220" cy="270" r="30" fill="#7888A8"/>
  <circle cx="220" cy="270" r="15" fill="#D6E0F5"/>
  <circle cx="380" cy="270" r="30" fill="#7888A8"/>
  <circle cx="380" cy="270" r="15" fill="#D6E0F5"/>
  <text x="300" y="340" font-family="Poppins,sans-serif" font-size="14" fill="#7888A8" text-anchor="middle">Vehicle Image Coming Soon</text>
</svg>"""

import os
os.makedirs('static/images/cars', exist_ok=True)
with open('static/images/cars/placeholder.jpg', 'w') as f:
    f.write(svg)
print("Placeholder created at static/images/cars/placeholder.jpg")
