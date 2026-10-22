"""Streamlit pieces shared by the screens — DESIGN v5 (task T9: the mockup PDF).

Design: background #F6F7F9 (theme, .streamlit/config.toml), white cards (radius 18, soft
shadow, no borders), system font (5.6), weights 400/500/600 only, line-height 1.4, primary #1F4E9D only for
main actions and selected chips, one 480 px column, Mongolian only. CSS hooks onto Streamlit's
`st-key-<key>` classes: a container whose key starts with "card_" becomes a white card, "grp_" a
white card of tappable rows ("act_" rows, divided by thin lines).

Hand-off between screens: a screen stores a plain value in st.session_state
(REC_PENDING, CARD_ID, SEARCH_PENDING) and calls st.switch_page. The target
screen reads it at the top of its run. Widget keys are not written from another
screen, because Streamlit drops the state of widgets not drawn in the last run.
"""

import base64
import html
import io
from contextlib import contextmanager
from datetime import date

import streamlit as st
from PIL import Image, UnidentifiedImageError  # pillow: installed with streamlit

from src.ui import api_client, auth, logic

# Folder is "views", NOT "pages": Streamlit auto-runs a folder named pages/
# in legacy mode, which skips app.py (sys.path setup and the login gate) when
# a page URL is opened directly.
HOME_PAGE = "views/home.py"
RECORD_PAGE = "views/record.py"
SEARCH_PAGE = "views/search.py"
CARD_PAGE = "views/card.py"
REMINDERS_PAGE = "views/reminders.py"
DASHBOARD_PAGE = "views/dashboard.py"

REC_PENDING = "rec_pending"        # {"identifier_type", "identifier", "card" | None}
REC_RESET = "rec_reset"            # True -> record screen starts at the camera step
CARD_ID = "card_id"                # vehicle shown on the card screen
SEARCH_PENDING = "search_pending"  # query to search on arrival
RECENT = "recent_vehicles"         # "Сүүлд үзсэн": [{id, identifier, company, status}], this session only
RECENT_MAX = 5
DIAG = "diag"                      # True -> record result shows the photo size (8.4, ?diag=1)

# DESIGN v5 (T9, mockup). Type: home title 26/600 · screen title 20/600 · section 13/600 grey
# (or 16/600 dark) · body 15/400 · labels 14/500 · big numbers 34/600 (status) and 26/600 (tiles).
# Max weight 600, line-height 1.4. Spacing: page 12/20/40, element 12, card padding 20, field 16.
CSS = """
<style>
:root {--ink:#111827; --ink2:#374151; --muted:#4B5563; --faint:#6B7280; --line:#EEF0F3; --fill:#F3F4F6;
  --pri:#1F4E9D; --pri-dark:#173B78; --pri-tint:#EAF0FA; --r:18px;
  --shadow:0 1px 2px rgba(16,24,40,.04), 0 4px 16px rgba(16,24,40,.05);}
.stApp, .stApp p, .stApp input, .stApp button, .stApp label {line-height: 1.4;}
/* 5.6: the phone's own system font (iPhone: San Francisco, Android: Roboto). Montserrat 400 has thin
   strokes and read as "light" on iPhone at 13-15 px; a system font also works when web fonts are
   blocked (Lockdown Mode) and needs no download. Material icon spans keep their icon font. */
body, body *:not([data-testid="stIconMaterial"]) {font-family: -apple-system, BlinkMacSystemFont,
  "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif !important;}
.stApp {font-weight: 400;}
.stApp input::placeholder, .stApp textarea::placeholder {color: var(--muted) !important; opacity: 1 !important;}
/* 8.1: iPhone Safari zooms the page in when a field under 16 px gets focus -> every field 16 px
   (bigger rules further down, e.g. liters 18 px, still win). touch-action: manipulation turns off
   double-tap zoom on tap targets only; pinch zoom stays (viewport meta is not touched). */
.stApp input, .stApp textarea, .stApp select, [data-baseweb="select"] > div {font-size: 16px !important;}
.stApp button, .stApp a, .stApp label, .stApp [role="button"], .stApp [role="option"],
  [data-baseweb="select"], [data-baseweb="popover"] li {touch-action: manipulation;}
/* page: no Streamlit top bar; 480 px column, centered */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {display: none !important;}
.block-container {padding: 12px 20px 40px !important; max-width: 480px;}
/* CSS-only markdown blocks are 0 px tall but still take a gap -> remove them from the layout */
[data-testid="stElementContainer"]:has(style) {display: none;}
[data-testid="stVerticalBlock"] {gap: 12px;}
[class*="st-key-card_"], [class*="st-key-grp_"], [class*="st-key-act_"] {margin-top: 4px;}
b, strong, th {font-weight: 600 !important;}
.stMarkdown p {margin: 0;}
[data-testid="stMarkdownContainer"] {margin-bottom: 0 !important;}  /* Streamlit's -1rem assumes a trailing <p> margin */

/* top row: back chevron + title on one line (inner screens) */
.st-key-topbar {min-height: 48px; gap: 4px !important; margin-bottom: 4px;}
.st-key-back button {min-height: 40px !important; width: 40px; padding: 0 !important; margin-left: -10px; color: var(--ink) !important;}
.st-key-back button p {position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);}  /* label for screen readers */
.st-key-back button [data-testid="stIconMaterial"] {font-size: 0 !important;}
/* 5.6: chevron drawn as a CSS mask (an image, not a font), so it shows even when icon fonts are blocked */
.st-key-back button::before {content: ""; width: 22px; height: 22px; background: currentColor;
  -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 -960 960 960'%3E%3Cpath d='M400-80 0-480l400-400 71 71-329 329 329 329-71 71Z'/%3E%3C/svg%3E") center / 18px no-repeat;
  mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 -960 960 960'%3E%3Cpath d='M400-80 0-480l400-400 71 71-329 329 329 329-71 71Z'/%3E%3C/svg%3E") center / 18px no-repeat;}
/* 5.6: other icons: if the icon font is blocked, the icon NAME ("keyboard") would show as text ->
   clip each icon to one 1em box (a loaded icon is exactly 1em wide, so nothing changes then) */
[data-testid="stIconMaterial"] {display: inline-block; width: 1em; overflow: hidden; white-space: nowrap; flex: none;}
.stHeading h1, .stHeading h2, .stHeading h3 {margin: 0 !important; padding: 0 !important;}
h1 {font-size: 20px !important; font-weight: 600 !important; letter-spacing: -.01em; line-height: 1.4 !important;}
.st-key-home_title h1 {font-size: 26px !important;}
/* section label: small grey (mockup «Энэ удаа», «Жолооч», «Түүх») */
h2, h3 {font-size: 14px !important; font-weight: 600 !important; color: var(--muted) !important; line-height: 1.4 !important;}
[data-testid="stElementContainer"]:has(> .stHeading h3) {margin: 8px 0 -4px 2px;}
.sec-dark {font-size: 16px; font-weight: 600; color: var(--ink); margin-top: 8px;}
.sec-row {display: flex; justify-content: space-between; align-items: baseline; margin: 8px 0 -4px;}
.sec-row .r {font-size: 13px; color: var(--muted);}
.hint {font-size: 14px; color: var(--muted); margin: -8px 0 0;}

/* widgets: labels 14/500 dark, inputs 52 px grey fill, no border (primary border on focus) */
[data-testid="stWidgetLabel"] {margin-bottom: 8px !important; min-height: 0 !important;}
[data-testid="stWidgetLabel"] p {font-size: 14px !important; font-weight: 500 !important; color: var(--ink2);}
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {
  border: 1px solid transparent !important; border-radius: 14px !important; background: var(--fill) !important;}
[data-baseweb="input"] {min-height: 52px;}
[data-baseweb="input"] input {font-size: 16px; padding-left: 16px;}  /* 16 px: iOS does not zoom */
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within, [data-baseweb="textarea"]:focus-within {
  border-color: var(--pri) !important;}
[data-testid="stNumberInputContainer"] {border-radius: 14px;}
.st-key-f_odometer_km button, .st-key-f_engine_hours button {display: none;}  /* typed, not stepped (mockup) */
.sub-note {font-size: 13px; color: var(--muted); margin-top: -8px;}
.warn-note {font-size: 13px; font-weight: 500; color: #A05A00;}

/* buttons: primary 54 px, radius 16, soft blue glow; secondary grey; tertiary = text link */
.stButton button, .stFormSubmitButton button, .stLinkButton a {min-height: 52px; border-radius: 16px; padding: 8px 16px;}
.stButton button p, .stFormSubmitButton button p, .stLinkButton a p {font-size: 16px; font-weight: 600;}
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primaryFormSubmit"] {
  min-height: 54px; border: none; box-shadow: 0 6px 16px rgba(31,78,157,.22);}
.stButton button[kind="secondary"], .stFormSubmitButton button[kind="secondaryFormSubmit"], .stLinkButton a {
  background: #fff; border: none; box-shadow: var(--shadow); color: var(--ink);}
[class*="st-key-card_"] .stButton button[kind="secondary"], [class*="st-key-card_"] .stLinkButton a {
  background: var(--fill); box-shadow: none; min-height: 44px; border-radius: 14px;}
[class*="st-key-card_"] .stButton button[kind="secondary"] p, [class*="st-key-card_"] .stLinkButton a p {font-size: 15px;}
.stButton button[kind="tertiary"] {min-height: 44px; padding: 0 4px; color: var(--pri);}
.stButton button[kind="tertiary"] p {font-size: 15px; font-weight: 600;}
.stButton button[kind="tertiary"]:hover {color: var(--pri-dark);}
.st-key-link_center {display: flex; justify-content: center;}

/* cards */
[class*="st-key-card_"] {background: #fff; border-radius: var(--r); padding: 20px; box-shadow: var(--shadow); gap: 16px;}
[class*="st-key-card_"] h3 {color: var(--ink) !important; font-size: 16px !important;}

/* pills (destinations, route): 40 px, round, grey; selected = primary */
[data-testid="stButtonGroup"] [role="radiogroup"], [data-testid="stButtonGroup"] > div {gap: 8px;}
[data-testid="stButtonGroup"] button {min-height: 40px; padding: 6px 18px; border: none; background: var(--fill); border-radius: 999px;}
[data-testid="stButtonGroup"] button p {font-size: 15px; font-weight: 500;}
[data-testid="stButtonGroup"] button[aria-checked="true"] {background: var(--pri) !important; color: #fff !important;}
.st-key-f_destination_id button:last-child:not([aria-checked="true"]) p {color: var(--muted);}  /* «Бусад» */
/* oil grade = segmented control: grey track, selected segment white */
.st-key-f_oil_choice, .st-key-f_oil_choice [data-testid="stButtonGroup"], .st-key-f_oil_choice div:has(> button) {width: 100% !important; max-width: none !important;}
.st-key-f_oil_choice div:has(> button) {display: flex; background: var(--fill); border-radius: 14px; padding: 4px; gap: 0 !important;}
.st-key-f_oil_choice button {flex: 1 1 0; min-width: 0; padding: 4px 2px !important; min-height: 44px; border-radius: 11px !important; background: transparent !important; color: var(--ink2) !important;}
.st-key-f_oil_choice button[aria-checked="true"] {background: #fff !important; color: var(--ink) !important; box-shadow: 0 1px 3px rgba(16,24,40,.12);}
.st-key-f_oil_choice button[aria-checked="true"] p {font-weight: 600;}
.st-key-f_oil_choice button p, .st-key-f_oil_choice button div {overflow: visible !important; text-overflow: clip !important; white-space: nowrap;}
/* liters: label left, stepper right */
.st-key-liters_row {align-items: center !important;}
.st-key-f_liters [data-testid="stNumberInputContainer"] {background: var(--fill); padding: 4px; height: 56px;}
.st-key-f_liters [data-testid="stNumberInputContainer"] > div:last-child {display: contents;}
.st-key-f_liters [data-testid="stNumberInputStepDown"] {order: -1;}
.st-key-f_liters [data-testid="stNumberInputStepDown"], .st-key-f_liters [data-testid="stNumberInputStepUp"] {
  width: 48px; height: 48px; border-radius: 11px; background: #fff; box-shadow: 0 1px 2px rgba(16,24,40,.08);}
.st-key-f_liters [data-baseweb="input"] {min-height: 48px; background: transparent !important;}
.st-key-f_liters input {text-align: center; font-size: 18px !important; font-weight: 600; padding: 0 !important;}
.st-key-liters_row .k {font-size: 15px; font-weight: 500;} .st-key-liters_row .s {font-size: 13px; color: var(--muted);}

[data-testid="stExpander"] details {border: none; background: transparent;}
[data-testid="stExpander"] summary {padding: 0; min-height: 32px;}
[data-testid="stExpander"] summary p {font-size: 15px; font-weight: 600; color: var(--pri);}
[data-testid="stExpander"] summary svg, [data-testid="stExpander"] summary [data-testid="stIconMaterial"] {display: none;}
[data-testid="stExpanderDetails"] {padding: 12px 0 0 !important;}
[data-testid="stFileUploaderDropzone"] {border: none; background: var(--fill); border-radius: 14px;}
[data-testid="stCameraInputButton"] {border: none !important; background: var(--fill);}

/* home: brand row, stats, action rows */
.brand {display: flex; align-items: center; gap: 12px; min-height: 44px; margin-bottom: 12px;}
.logo {width: 32px; height: 32px; border-radius: 10px; background: var(--pri); color: #fff; font-size: 13px; font-weight: 600;
  display: flex; align-items: center; justify-content: center; flex: none;}
.bname {font-size: 15px; font-weight: 500; color: var(--ink2);}
.bdate {margin-left: auto; font-size: 13px; color: var(--muted); text-align: right;}
.greet {font-size: 15px; color: var(--muted); margin-top: -6px;}
.stats {display: grid; grid-template-columns: repeat(3, 1fr); background: #fff; border-radius: var(--r); box-shadow: var(--shadow);
  padding: 16px 0; margin-top: 8px;}
.stats > div {padding: 0 16px;} .stats > div + div {border-left: 1px solid var(--line);}
.stats .k {font-size: 13px; color: var(--muted);} .stats .v {font-size: 26px; font-weight: 600; margin-top: 4px; line-height: 1.2;}
/* tappable rows: HTML row + the real button/link stretched over it (one tap target, keeps its label) */
[class*="st-key-act_"] {position: relative; background: #fff; border-radius: var(--r); padding: 16px 20px;
  box-shadow: var(--shadow); gap: 0 !important;}
.st-key-act_record {background: var(--pri); box-shadow: 0 8px 20px rgba(31,78,157,.25); padding: 20px;}
[class*="st-key-act_"] [data-testid="stElementContainer"]:has(.stButton, .stPageLink) {
  position: absolute; inset: 0; margin: 0; z-index: 2; height: 100%;}
[class*="st-key-act_"] .stButton, [class*="st-key-act_"] .stPageLink {height: 100%;}
[class*="st-key-act_"] .stButton button, [class*="st-key-act_"] .stPageLink a {width: 100%; height: 100%; min-height: 0;
  background: transparent !important; border: none !important; box-shadow: none !important; border-radius: inherit;}
[class*="st-key-act_"] .stButton button *, [class*="st-key-act_"] .stPageLink a * {opacity: 0;}
[class*="st-key-grp_"] {background: #fff; border-radius: var(--r); box-shadow: var(--shadow); gap: 0 !important; overflow: hidden;}
[class*="st-key-grp_"] [class*="st-key-act_"] {background: transparent; box-shadow: none; border-radius: 0; margin: 0;}
[class*="st-key-grp_"] [data-testid="stLayoutWrapper"] + [data-testid="stLayoutWrapper"] [class*="st-key-act_"]::before {
  content: ""; position: absolute; top: 0; left: 20px; right: 20px; border-top: 1px solid var(--line);}
.st-key-grp_nav [data-testid="stLayoutWrapper"] + [data-testid="stLayoutWrapper"] [class*="st-key-act_"]::before {left: 84px; right: 0;}
.act {display: flex; align-items: center; gap: 16px; min-height: 48px;}
.act-ic {width: 48px; height: 48px; border-radius: 14px; display: flex; align-items: center; justify-content: center;
  background: var(--pri-tint); color: var(--pri); flex: none;}
.act-ic.amber {background: #FFF4E0; color: #A05A00;} .act-ic.green {background: #E8F5EE; color: #1E7A4C;}
.act-ic svg {width: 24px; height: 24px; fill: currentColor;}
.act-t {font-size: 17px; font-weight: 600; color: var(--ink);}
.act-s {font-size: 14px; color: var(--muted); margin-top: 2px;}
.act-go {margin-left: auto; color: var(--faint); display: flex;} .act-go svg {width: 22px; height: 22px; fill: currentColor;}
.badge {margin-left: auto; min-width: 26px; height: 26px; padding: 0 8px; border-radius: 13px; background: #B42318; color: #fff;
  font-size: 13px; font-weight: 600; display: flex; align-items: center; justify-content: center;}
.st-key-act_record .act-ic {background: rgba(255,255,255,.16); color: #fff;}
.st-key-act_record .act-t {color: #fff; font-size: 18px;} .st-key-act_record .act-s {color: #DCE5F5;}
.st-key-act_record .act-go {color: #fff;}
.vrow {display: flex; align-items: center; gap: 12px; min-height: 36px;}
.vrow .co {flex: 1; min-width: 0; font-size: 14px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.st {display: inline-flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 500; white-space: nowrap;}

/* plate + chips */
.plate {display: inline-block; font-size: 15px; font-weight: 600; letter-spacing: .02em; font-variant-numeric: tabular-nums;
  background: var(--fill); border-radius: 10px; padding: 6px 12px; white-space: nowrap; color: var(--ink);}
.plate.lg {font-size: 24px; background: #fff; border: 1px solid #E5E7EB; border-radius: 14px; padding: 6px 16px;}
.plate-row {display: flex; flex-wrap: wrap; align-items: center; gap: 10px;}
.chip {display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 999px; font-size: 13px; font-weight: 500;
  background: var(--fill); color: var(--ink2);}
.chip.known {background: #E8F5EE; color: #1E7A4C;} .chip.new {background: var(--pri-tint); color: var(--pri);}
.dot {display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex: none;}
.muted {color: var(--muted); font-size: 14px;}
.line {color: var(--muted); font-size: 15px; margin-top: -4px;}
.pill-st {display: inline-flex; align-items: center; padding: 4px 12px; border-radius: 999px; font-size: 13px; font-weight: 500; white-space: nowrap;}

/* vehicle header in the forms */
.vh {display: flex; align-items: center; gap: 14px;}
.vh-tile {width: 52px; height: 52px; border-radius: 14px; background: linear-gradient(160deg, #3A4152, #1F2430); flex: none;
  display: flex; align-items: center; justify-content: center;}
.vh-tile i {width: 26px; height: 11px; border-radius: 3px; background: #fff;}
.vh-id {font-size: 19px; font-weight: 600; letter-spacing: .01em;}
.vh-sub span {display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;}
.vh-sub {display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; margin-top: 2px;}
.vh-big {font-size: 22px; font-weight: 600; letter-spacing: .01em;}
.st-key-vh_row {align-items: center !important; flex-wrap: nowrap !important;}
.st-key-vh_row > [data-testid="stElementContainer"]:first-child {flex: 1 1 auto; min-width: 0; width: auto !important;}
.st-key-vh_row > [data-testid="stElementContainer"]:last-child {flex: none; width: auto !important;}
.strip {position: relative; height: 84px; border-radius: var(--r); overflow: hidden; background: linear-gradient(160deg, #4A5160, #1F2430);}
.strip img {width: 100%; height: 100%; object-fit: cover; display: block;}
.strip .ok {position: absolute; top: 10px; left: 12px; display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px;
  border-radius: 10px; background: rgba(17,24,39,.6); color: #fff; font-size: 13px; font-weight: 500;}
.strip .ok svg {width: 16px; height: 16px; fill: currentColor;}

/* 8.4 record start + result (Ari's mockup) */
.st-key-rec_alt {flex-wrap: nowrap !important; gap: 12px !important; align-items: stretch;}
.st-key-rec_alt > [data-testid="stElementContainer"] {flex: 1 1 0 !important; min-width: 0; width: auto !important;}
.st-key-btn_manual button {min-height: 56px; height: 56px; border: 1px solid #D5D9E0 !important; border-radius: 14px;
  background: #fff; box-shadow: none !important;}
.st-key-btn_manual button p {font-weight: 500;}
.st-key-link_fleet_capture button {padding: 0 4px;}
.rec-photo {height: 200px; border-radius: var(--r); overflow: hidden; background: #2B2F36;}
.rec-photo img {width: 100%; height: 100%; object-fit: contain; display: block;}
.rec-banner {display: flex; align-items: center; gap: 8px; border-radius: 12px; padding: 12px 14px; font-size: 15px; font-weight: 500;}
.rec-banner.ok {background: #E7F5EC; color: #14532D;}
.rec-banner.warn {background: #FFF4E5; color: #7A3E00;}
.rec-banner svg {width: 20px; height: 20px; fill: currentColor; flex: none;}
/* Streamlit 1.64 text input = react-aria: the visible box is stTextInputRootElement */
[class*="st-key-plate_field"] [data-testid="stTextInputRootElement"] {height: 64px; background: #fff !important;
  border: 2px solid #D5D9E0 !important; border-radius: 14px !important;}
.st-key-plate_field_read [data-testid="stTextInputRootElement"] {border-color: var(--pri) !important;}
[class*="st-key-plate_field"] [data-testid="stTextInputRootElement"]:focus-within {border-color: var(--pri) !important;}
.stApp [class*="st-key-plate_field"] input {height: 100%; font-size: 28px !important; font-weight: 600; letter-spacing: 2px;
  text-align: center; padding: 0 8px;}
.stApp [class*="st-key-plate_field"] input::placeholder {font-weight: 400; letter-spacing: 0;}

/* status block (card) + arrival block (recognized truck) */
.pc {border-radius: 16px; padding: 18px 20px;}
.pc-top {display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600;}
.pc-big {font-size: 34px; font-weight: 600; line-height: 1.2; margin: 8px 0 4px;}
.pc-big span {font-size: 16px; font-weight: 500;}
.pc-date {font-size: 15px; font-weight: 500;}
.pc-range {font-size: 13px;}
.pc-note {font-size: 13px; margin-top: 10px;}
.pc-pending {font-size: 15px; font-weight: 500; color: var(--ink2);}
.pc.sm .pc-big {font-size: 28px; margin: 6px 0 2px;} .pc.sm .pc-date {font-size: 13px;}

/* label · value rows (card facts, «Өмнөх удаа», oil/driver) */
.kv > div {display: flex; justify-content: space-between; align-items: baseline; gap: 16px; padding: 14px 0;}
.kv > div + div {border-top: 1px solid var(--line);}
.kv > div:first-child {padding-top: 0;} .kv > div:last-child {padding-bottom: 0;}
.kv .k {font-size: 15px; color: var(--muted); white-space: nowrap;}
.kv .v {font-size: 15px; font-weight: 600; text-align: right; overflow-wrap: anywhere;}
.kv.sm .v {font-weight: 500; font-size: 14px;} .kv.sm .k {font-size: 14px;} .kv.top {border-top: 1px solid var(--line); padding-top: 14px;}

/* history timeline */
.tl > div {position: relative; padding: 0 0 18px 28px;}
.tl > div:last-child {padding-bottom: 0;}
.tl > div::before {content: ""; position: absolute; left: 3px; top: 7px; width: 9px; height: 9px; border-radius: 50%; background: #D1D5DB;}
.tl > div:first-child::before {background: var(--pri);}
.tl > div:not(:last-child)::after {content: ""; position: absolute; left: 7px; top: 22px; bottom: 4px; width: 1px; background: #E5E7EB;}
.tl .h {display: flex; justify-content: space-between; gap: 12px;}
.tl .d {font-size: 16px; font-weight: 500;} .tl .km {font-size: 14px; color: var(--muted); white-space: nowrap;}
.tl .s {font-size: 14px; color: var(--muted); margin-top: 2px;}

/* reminders / dashboard tiles */
.tiles {display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 4px;}
.tiles.two {grid-template-columns: repeat(2, 1fr);}
.tiles > div {background: #fff; border-radius: var(--r); box-shadow: var(--shadow); padding: 16px 18px;}
.tiles .v {font-size: 26px; font-weight: 600; line-height: 1.2;} .tiles .k {font-size: 14px; color: var(--muted); margin-top: 4px;}
.tiles .k .dot {margin-right: 6px;}
.rem {display: flex; align-items: center; gap: 12px;}
.rem.sep {border-top: 1px solid var(--line); padding-top: 16px; margin-top: 4px;}
.rem .who {flex: 1; min-width: 96px;} .rem .n {font-size: 15px; font-weight: 500;}
.rem .m {font-size: 13px; color: var(--muted);}
[data-testid="stCode"] pre {background: #F6F7F9; border: none; border-radius: 12px; font-size: 14px;}
[data-testid="stCode"] pre, [data-testid="stCode"] code {font-family: -apple-system, BlinkMacSystemFont,
  "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif !important;}
.note-line {display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted);}

/* success */
.done {width: 64px; height: 64px; margin: 8px auto; border-radius: 50%; background: #E8F5EE; color: #1E7A4C;
  display: flex; align-items: center; justify-content: center; font-size: 32px; font-weight: 600;}
.done-title {text-align: center; font-size: 22px; font-weight: 600; margin: 0 0 16px;}
.center {display: flex; justify-content: center;}
[class*="st-key-photo_preview"] img {border-radius: 12px; object-fit: cover;}
/* visible focus ring (keyboard / switch users), reduced motion */
button:focus-visible, input:focus-visible, a:focus-visible, [role="radio"]:focus-visible {outline: 3px solid var(--pri) !important; outline-offset: 2px;}
@media (prefers-reduced-motion: reduce) {* {transition: none !important; animation: none !important;}}
</style>
"""

# Material Symbols paths (Apache 2.0), inline so no icon font/class is needed in HTML blocks.
ICONS = {
    "camera": "M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4zM9 2 7.17 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 "
              "2-.9 2-2V6c0-1.1-.9-2-2-2h-3.17L15 2H9zm3 15c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5z",
    "search": "M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 "
              "4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
    "bell": "M12 22c1.1 0 2-.9 2-2h-4c0 1.1.89 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 "
            "1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z",
    "chevron": "M10 6 8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z",
    "check": "M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
    "send": "M2.01 21 23 12 2.01 3 2 10l15 2-15 2z",
    "chart": "M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z",
}


def icon(name: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="{ICONS[name]}"/></svg>'


def inject_css() -> None:
    """DESIGN v5 tweaks on top of the theme (.streamlit/config.toml)."""
    st.markdown(CSS, unsafe_allow_html=True)


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


# --- layout ------------------------------------------------------------------------

def header(title: str, back: str | None = None) -> None:
    """Screen header: back chevron (inner screens) + title 20/600 on one row (mockup)."""
    with st.container(key="topbar", horizontal=True, vertical_alignment="center"):
        if back:
            if st.button("Буцах", key="back", type="tertiary", icon=":material/arrow_back_ios_new:"):
                st.switch_page(back)
        st.title(title, anchor=False)


def home_header(today: date) -> None:
    """Home: «ГЭ» mark + «Гео-Эксперт» + today's date, then the big greeting."""
    html_block(f'<div class="brand"><span class="logo">ГЭ</span><span class="bname">Гео-Эксперт</span>'
               f'<span class="bdate">{html.escape(logic.today_text(today))}</span></div>')
    with st.container(key="home_title"):
        st.title("Сайн байна уу", anchor=False)


def section(title: str, right: str = "", hint: str = "") -> None:
    """Dark 16/600 section title (+ optional grey text on the right, grey hint below)."""
    right_html = f'<span class="r">{html.escape(right)}</span>' if right else ""
    hint_html = f'<div class="hint" style="margin-top:4px">{html.escape(hint)}</div>' if hint else ""
    html_block(f'<div class="sec-row"><div><div class="sec-dark" style="margin:0">{html.escape(title)}</div>'
               f'{hint_html}</div>{right_html}</div>')


def kv_rows(pairs: list[tuple[str, str]], extra_class: str = "") -> str:
    """Label left (grey) · value right (600), thin lines between (card facts, oil/driver)."""
    rows = "".join(f'<div><span class="k">{html.escape(k)}</span><span class="v">{html.escape(v)}</span></div>'
                   for k, v in pairs)
    return f'<div class="kv {extra_class}">{rows}</div>'


def known_chip_html(card: dict | None) -> str:
    """«Бүртгэлтэй · N удаа ирсэн» or «Шинэ машин» (small tinted chip)."""
    if card:
        text, cls = f"Бүртгэлтэй · {card.get('service_count', 0)} удаа ирсэн", "known"
    else:
        text, cls = "Шинэ машин", "new"
    return f'<span class="chip {cls}">{html.escape(text)}</span>'


def segment_chip_html(segment: str | None, service_count: int | None = None) -> str:
    """Small grey chip next to the plate: colored dot + «Байнгын · 3 удаа» (word, never color alone)."""
    parts = [logic.segment_label(segment)] if segment else []
    if service_count:
        parts.append(f"{service_count} удаа")
    if not parts:
        return ""
    return f'<span class="chip">{_dot(logic.SEGMENT_DOTS.get(segment))}{html.escape(" · ".join(parts))}</span>'


def _dot(color: str | None) -> str:
    return f'<i class="dot" style="background:{color}"></i>' if color else ""


def plate_box(identifier: str, *chips: str, large: bool = False) -> None:
    """Plate chip (grey fill, 600, spaced letters; large = white with a thin line) + small chips beside it."""
    cls = "plate lg" if large else "plate"
    html_block(f'<div class="plate-row"><span class="{cls}">{html.escape(identifier or "")}</span>{"".join(chips)}</div>')


def status_html(status: str | None) -> str:
    """«● Хэтэрсэн» in the status color ('' when there is no prediction)."""
    if status not in logic.STATUS_COLORS:
        return ""
    fg = logic.STATUS_COLORS[status][0]
    return f'<span class="st" style="color:{fg}">{_dot(fg)}{html.escape(logic.PREDICTION_STATUS_LABELS[status])}</span>'


@contextmanager
def action_card(key: str, icon_name: str, title: str, subtitle: str, tone: str = "", badge: int | None = None):
    """Row card: icon + title + 1-line subtitle + chevron (or a red count badge). The caller puts
    the real st.button / st.page_link inside; CSS stretches it over the whole row (one tap target,
    keeps its accessible label)."""
    end = f'<span class="badge">{badge}</span>' if badge else f'<span class="act-go">{icon("chevron")}</span>'
    with st.container(key=key):
        html_block(
            f'<div class="act"><span class="act-ic {tone}">{icon(icon_name)}</span>'
            f'<div><div class="act-t">{html.escape(title)}</div><div class="act-s">{html.escape(subtitle)}</div></div>'
            f'{end}</div>'
        )
        yield


def recent_rows(key_prefix: str) -> bool:
    """«Сүүлд үзсэн» rows in one white card: plate · company · status; tap -> card. False if empty."""
    recent = st.session_state.get(RECENT, [])
    if not recent:
        return False
    with st.container(key=f"grp_{key_prefix}"):
        for item in recent:
            with st.container(key=f"act_{key_prefix}_{item['id']}"):
                html_block(f'<div class="vrow"><span class="plate">{html.escape(item["identifier"])}</span>'
                           f'<span class="co">{html.escape(item["company"])}</span>{status_html(item.get("status"))}</div>')
                # width="stretch": a content-width button left the right end of the row untappable (5.9b)
                if st.button(f"{item['identifier']} · {item['company']}", key=f"{key_prefix}_{item['id']}",
                             width="stretch"):
                    go_card(item["id"])
    return True


def logout_button() -> None:
    """«Гарах» at the bottom of a screen (only when login is on)."""
    if auth.login_required():
        if st.button("Гарах", key="logout", type="tertiary"):
            st.session_state["authed"] = False
            st.rerun()


# --- navigation ----------------------------------------------------------------------

def go_record(identifier_type: str, identifier: str, card: dict | None) -> None:
    """Open the service form for this vehicle (card=None -> new vehicle)."""
    st.session_state[REC_PENDING] = {"identifier_type": identifier_type, "identifier": identifier, "card": card}
    st.switch_page(RECORD_PAGE)


def go_record_start() -> None:
    """Open the record screen at the camera step (a new truck)."""
    st.session_state[REC_RESET] = True
    st.switch_page(RECORD_PAGE)


def go_card(vehicle_id: int) -> None:
    st.session_state[CARD_ID] = vehicle_id
    st.switch_page(CARD_PAGE)


def remember_viewed(card: dict) -> None:
    """Put this vehicle first in «Сүүлд үзсэн» (session only, max RECENT_MAX)."""
    item = {"id": card["id"], "identifier": card["identifier"],
            "company": (card.get("company") or {}).get("name", ""),
            "status": (card.get("prediction") or {}).get("status")}
    recent = [r for r in st.session_state.get(RECENT, []) if r["id"] != item["id"]]
    st.session_state[RECENT] = [item, *recent][:RECENT_MAX]


# --- API helpers ---------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def cached_destinations() -> list[dict]:
    """GET /destinations, cached 5 minutes (the list rarely changes)."""
    return api_client.destinations()


def show_api_error(exc: api_client.ApiError) -> None:
    for message in logic.error_messages(exc.status, exc.detail):
        st.error(message)


def recognize_photo_box(photo) -> tuple[str, bool, str, list[float] | None]:
    """Send an uploaded/camera photo to POST /plates/recognize.

    Returns (plate, needs_manual, message, plate box or None). Any API failure ->
    ("", True, message, None): the oil changer types the plate, so recognition can never block the flow.
    """
    try:
        result = api_client.recognize_plate(photo.getvalue(), photo.name or "photo.jpg",
                                            logic.photo_content_type(photo.name, photo.type))
    except api_client.ApiError as exc:
        return "", True, logic.recognize_error_message(exc.status), None
    box = (result.get("detection") or {}).get("box")
    return (*logic.recognize_outcome(result), box)


def recognize_photo(photo) -> tuple[str, bool, str]:
    """(plate, needs_manual, message) — recognize_photo_box without the box."""
    return recognize_photo_box(photo)[:3]


def _decodable(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return False
    return True


def photo_preview(data: bytes | None, name: str | None = None) -> None:
    """Small preview of the photo just taken/uploaded. Never crashes the flow: a photo the
    browser-side decoder cannot read (e.g. iPhone HEIC — the API converts it, the UI has no
    HEIC decoder) shows a text line instead."""
    if not data:
        return
    if not _decodable(data):
        html_block(f'<span class="muted">Зураг: {html.escape(name or "")} (урьдчилж харах боломжгүй)</span>')
        return
    with st.container(key="photo_preview"):
        st.image(data, width=120)  # thumbnail


def plate_strip(data: bytes | None, box: list[float] | None) -> None:
    """Recognized truck: dark strip with the plate area of the photo + «✓ Автоматаар уншсан».

    The crop is made here, in memory, and sent only to this browser (D-070). No photo or an
    undecodable one (HEIC) -> the strip without an image.
    """
    jpeg = _plate_crop(data, box, zoom=2.6, aspect=4.2, size=(900, 300))
    img_html = f'<img alt="" src="data:image/jpeg;base64,{base64.b64encode(jpeg).decode()}">' if jpeg else ""
    html_block(f'<div class="strip">{img_html}<span class="ok">{icon("check")}Автоматаар уншсан</span></div>')


def _plate_crop(data: bytes | None, box: list[float] | None, zoom: float, aspect: float,
                size: tuple[int, int]) -> bytes | None:
    """JPEG of the area around the plate box (zoom x box width, width/height = aspect), or the
    whole photo when there is no box; shrunk to fit `size`. In memory only (D-070).
    None when there is no photo or it cannot be decoded (HEIC)."""
    if not data or not _decodable(data):
        return None
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        if box and len(box) == 4:
            x1, y1, x2, y2 = box
            cx, cy, w = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, 1) * zoom
            h = w / aspect
            img = img.crop((max(cx - w / 2, 0), max(cy - h / 2, 0),
                            min(cx + w / 2, img.width), min(cy + h / 2, img.height)))
        img.thumbnail(size)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def photo_view(data: bytes | None, box: list[float] | None, name: str | None = None) -> None:
    """Result screen (8.4): the photo in a dark 200 px box — zoomed to the plate when the
    detector found one, else the whole photo. Undecodable (HEIC) -> one text line."""
    if not data:
        return
    jpeg = _plate_crop(data, box, zoom=3.0, aspect=2.2, size=(900, 420))
    if jpeg is None:
        html_block(f'<span class="muted">Зураг: {html.escape(name or "")} (урьдчилж харах боломжгүй)</span>')
        return
    html_block(f'<div class="rec-photo"><img alt="Машины зураг" '
               f'src="data:image/jpeg;base64,{base64.b64encode(jpeg).decode()}"></div>')


# --- vehicle card parts ------------------------------------------------------------------

def render_prediction(prediction: dict | None) -> None:
    """Status block on a soft tint: dot + status word (never color alone), «5 хоног хоцорсон»
    34/600, «Солих ёстой байсан: 10-р сарын 7», method note; grey line when null."""
    v = logic.prediction_view(prediction)
    if v["pending"]:
        body = f'<div class="pc-pending">{html.escape(v["big"])}</div>'
    else:
        body = (
            f'<div class="pc-top">{_dot(v["fg"])}{html.escape(v["status_label"])}</div>'
            f'<div class="pc-big">{html.escape(v["big"])} <span>{html.escape(v["sub"])}</span></div>'
            f'<div class="pc-date">{html.escape(v["date_line"])}</div>'
            + (f'<div class="pc-range">{html.escape(v["range_line"])}</div>' if v["range_line"] else "")
            + f'<div class="pc-note">{html.escape(v["note"])}</div>'
        )
    html_block(f'<div class="pc" style="background:{v["bg"]};color:{v["fg"]}">{body}</div>')


def render_arrival(prediction: dict | None) -> None:
    """Recognized truck: «Цагтаа ирсэн · 2 хоног эрт ирсэн · Таамаглаж байсан огноо: …» (nothing when null)."""
    a = logic.arrival_view(prediction)
    if not a:
        return
    html_block(
        f'<div class="pc sm" style="background:{a["bg"]};color:{a["fg"]}">'
        f'<div class="pc-top">{_dot(a["fg"])}{html.escape(a["label"])}</div>'
        f'<div class="pc-big">{html.escape(a["big"])} <span>{html.escape(a["sub"])}</span></div>'
        f'<div class="pc-date">Таамаглаж байсан огноо: {html.escape(a["date"])}</div></div>'
    )


def render_tiles(card: dict) -> None:
    """4 fact rows (label left, value right): last change, «15W-40 · ердийн 32 л», destination, driver."""
    last = card.get("last_service") or {}
    pairs = [
        ("Сүүлд солисон", last.get("service_date") or logic.NOT_GIVEN),
        ("Тос", logic.oil_pair_text(last, card.get("usual_liters"))),
        ("Чиглэл", logic.service_destination_text(last) if last else logic.NOT_GIVEN),
        ("Жолооч", logic.driver_text(last.get("driver_name"), last.get("driver_phone"))),
    ]
    with st.container(key="card_facts"):
        html_block(kv_rows(pairs))


def render_history(history: list[dict]) -> None:
    """«Түүх»: timeline, newest first (blue dot), date + km, then oil · liters · destination."""
    st.subheader("Түүх")
    with st.container(key="card_history"):
        if not history:
            html_block('<span class="muted">Түүх алга.</span>')
            return
        rows = "".join(
            f'<div><div class="h"><span class="d">{html.escape(s.get("service_date", ""))}</span>'
            f'<span class="km">{html.escape(logic.service_meter_text(s))}</span></div>'
            f'<div class="s">{html.escape(" · ".join([s.get("oil_grade") or logic.NOT_GIVEN, logic.format_number(s.get("liters"), "л"), logic.service_destination_text(s)]))}</div></div>'
            for s in history
        )
        html_block(f'<div class="tl">{rows}</div>')
