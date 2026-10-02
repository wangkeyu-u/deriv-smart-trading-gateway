# Deriv Gateway Interface

## Direction

A compact technical workspace for repeated market inspection. Dark graphite and blue-gray surfaces reduce large-area glare; cool blue accents identify actions and selection. No decorative glow, green theme, or dashboard card wall.

## Tokens

- Canvas: `#0b101b`
- Surface: `#121b2c`
- Raised: `#19243a`
- Border: `#34445e`
- Text: `#e8eef9`
- Secondary: `#afbdd2`
- Accent: `#83b4ff`
- Accent ink: `#0b1830`
- Error: `#ff969d`; warning: `#edc58d`

## Typography

System sans, PingFang SC / Microsoft YaHei for Chinese. Body 15–16px; section title 26px; labels 14px. Monospace is reserved for prices, identifiers and code. 1.6 line height for explanations.

## Layout

Maximum content width 1160px. Compact brand/settings header; four workspace links. Analysis presents scenario and symbol, question, one submit action, then the latest result. Optional budget/news controls are collapsed. Settings use an explicit header popover; history belongs to Records.

Draft question, custom instrument, review direction and budget persist across workspace changes. Results label prices as snapshots with an explicit UTC+8 timestamp. History shows one selected saved result, its evidence and export; reusing inputs returns to Analysis and waits for an explicit submit.

## Components

8px form/button radius; 12px primary result surface. Native Streamlit widgets share colors, focus ring and 42px interaction height. Selected segments have a blue-tinted background and clear text. Disabled controls remain recognizable. No nested decorative cards. Results prioritize stance, reason, price and observed direction; rule vote shares and raw traces are secondary.

## Responsive and motion

At 640px and below, settings remains easy to reach, controls stack, navigation wraps without horizontal overflow. Transitions last 160ms and only indicate hover/focus. Reduced motion disables transitions. No decorative animation or autoplay visualization.

## Implementation

`ui/theme.css` is the common surface/widget style; `.streamlit/config.toml` supplies native theme defaults. `web_app.py` uses the same colors for Plotly and the optional graph canvas. Trading approval shows the persisted parameters and requires an explicit submit action. Order status, read-only reconciliation and global HALTED stay visible in Orders; the existing colors and layout are retained.
