import tkinter as tk
from tkinter import ttk, messagebox
from concurrent.futures import ThreadPoolExecutor, as_completed
from ddgs import DDGS

import json
import os
import re
import threading
import webbrowser
import time
from urllib.parse import urlparse


# ============================================================
# SETTINGS
# ============================================================

APP_FOLDER = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(APP_FOLDER, "seen_giveaways.json")

MAX_WORKERS = 6
MAX_RESULTS_PER_SEARCH = 10
SEARCH_TIMEOUT = 8
MAX_RETRIES = 1

# Searches cover different types of UK giveaways.
SEARCHES = [
    '"giveaway" UK "enter"',
    '"competition" UK "win a"',
    '"win" UK "prize" giveaway',
    '"free prize" UK competition',
    '"win" UK "competition"',
    '"giveaway" UK gaming PS5 Xbox PC',
]


# ============================================================
# KEYWORDS
# ============================================================

GIVEAWAY_WORDS = [
    "giveaway",
    "give away",
    "competition",
    "contest",
    "win",
    "winner",
    "prize",
    "enter",
    "draw",
    "sweepstake",
]

CAPTCHA_WORDS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "cloudflare turnstile",
    "verify you are human",
]

AUTOMATION_BLOCK_WORDS = [
    "no bots",
    "no automated",
    "automated entries",
    "automatic entries",
    "automated entry",
    "bots prohibited",
    "bot prohibited",
    "script",
    "scripts",
    "software",
    "mechanical",
    "bulk entries",
    "bulk entry",
    "third party entry",
    "third-party entry",
    "entries generated",
    "automated system",
]

SOCIAL_PLATFORMS = [
    "twitter.com",
    "x.com",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "youtube.com",
]

# Categories used by the application.
CATEGORIES = {
    "Gaming": [
        "gaming",
        "ps5",
        "ps4",
        "xbox",
        "nintendo",
        "switch",
        "steam",
        "gaming pc",
        "graphics card",
        "gpu",
        "rtx",
        "geforce",
        "playstation",
        "controller",
        "headset",
    ],

    "Technology": [
        "laptop",
        "computer",
        "pc",
        "phone",
        "iphone",
        "ipad",
        "samsung",
        "android",
        "technology",
        "tech",
        "tablet",
        "monitor",
        "keyboard",
        "mouse",
        "camera",
    ],

    "Money": [
        "cash",
        "£",
        "pounds",
        "money",
        "voucher",
        "gift card",
        "amazon voucher",
        "paypal",
    ],

    "Travel": [
        "holiday",
        "hotel",
        "travel",
        "flight",
        "flights",
        "trip",
        "hotel stay",
        "break",
        "vacation",
    ],

    "Food & Drink": [
        "restaurant",
        "meal",
        "food",
        "drink",
        "pizza",
        "takeaway",
        "supermarket",
        "tesco",
        "asda",
        "sainsbury",
        "morrisons",
    ],

    "Beauty": [
        "beauty",
        "makeup",
        "cosmetics",
        "skincare",
        "perfume",
        "hair",
    ],

    "Home": [
        "home",
        "furniture",
        "sofa",
        "bed",
        "kitchen",
        "garden",
        "appliance",
        "tv",
        "television",
    ],

    "Cars": [
        "car",
        "vehicle",
        "motor",
        "motoring",
        "fuel",
        "petrol",
        "diesel",
    ],

    "Clothing": [
        "clothing",
        "fashion",
        "shoes",
        "trainers",
        "sneakers",
        "jacket",
        "dress",
        "clothes",
    ],

    "Pets": [
        "dog",
        "cat",
        "pet",
        "pet food",
        "pet supplies",
    ],
}


# ============================================================
# FILE HANDLING
# ============================================================

def load_seen():
    """Load previously seen giveaway URLs."""

    try:
        if not os.path.exists(SEEN_FILE):
            return set()

        with open(SEEN_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return set(data)

    except Exception:
        pass

    return set()


def save_seen(seen):
    """Save previously seen URLs."""

    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as file:
            json.dump(
                sorted(list(seen)),
                file,
                indent=2,
                ensure_ascii=False
            )

        return True

    except Exception as error:
        print(f"Could not save seen giveaways: {error}")
        return False


# ============================================================
# TEXT HELPERS
# ============================================================

def normalise_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def looks_like_giveaway(title, description):
    text = normalise_text(
        f"{title} {description}"
    ).lower()

    return any(
        word in text
        for word in GIVEAWAY_WORDS
    )


def get_category(title, description):
    text = normalise_text(
        f"{title} {description}"
    ).lower()

    matches = []

    for category, keywords in CATEGORIES.items():

        for keyword in keywords:

            if keyword.lower() in text:
                matches.append(category)
                break

    if not matches:
        return "General"

    return matches[0]


# ============================================================
# PRIZE / VALUE DETECTION
# ============================================================

def extract_value(text):
    """
    Attempts to find monetary prize values.

    Examples:
        £500
        £1,000
        £10,000
        $500
        €500
        500 pounds

    Dollar/euro values are converted approximately for display.
    """

    text = normalise_text(text)

    values = []

    # £ values
    pound_matches = re.findall(
        r"£\s?[\d,]+(?:\.\d{1,2})?",
        text,
        flags=re.IGNORECASE
    )

    for value in pound_matches:
        cleaned = value.replace("£", "").replace(",", "").strip()

        try:
            amount = float(cleaned)
            values.append(
                f"£{amount:,.0f}"
                if amount.is_integer()
                else f"£{amount:,.2f}"
            )
        except ValueError:
            pass

    # "500 pounds"
    pound_word_matches = re.findall(
        r"(\d[\d,]*(?:\.\d+)?)\s+pounds?",
        text,
        flags=re.IGNORECASE
    )

    for value in pound_word_matches:

        try:
            amount = float(value.replace(",", ""))

            values.append(
                f"£{amount:,.0f}"
                if amount.is_integer()
                else f"£{amount:,.2f}"
            )

        except ValueError:
            pass

    # Dollar values.
    dollar_matches = re.findall(
        r"\$\s?[\d,]+(?:\.\d{1,2})?",
        text
    )

    for value in dollar_matches:

        try:
            amount = float(
                value.replace("$", "")
                .replace(",", "")
                .strip()
            )

            # Approximate USD -> GBP display conversion.
            gbp = amount * 0.74

            values.append(
                f"≈ £{gbp:,.0f}"
            )

        except ValueError:
            pass

    # Euro values.
    euro_matches = re.findall(
        r"€\s?[\d,]+(?:\.\d{1,2})?",
        text
    )

    for value in euro_matches:

        try:
            amount = float(
                value.replace("€", "")
                .replace(",", "")
                .strip()
            )

            # Approximate EUR -> GBP display conversion.
            gbp = amount * 0.86

            values.append(
                f"≈ £{gbp:,.0f}"
            )

        except ValueError:
            pass

    # Remove duplicates.
    unique = []

    for value in values:
        if value not in unique:
            unique.append(value)

    if not unique:
        return "Value not detected"

    return ", ".join(unique[:5])


# ============================================================
# RULE DETECTION
# ============================================================

def extract_rules(title, description):
    """
    Attempts to identify common giveaway requirements.
    """

    text = normalise_text(
        f"{title} {description}"
    )

    lower = text.lower()

    rules = []

    rule_patterns = [
        ("Follow required", r"\bfollow\b"),
        ("Like required", r"\blike\b"),
        ("Repost/retweet required", r"\b(retweet|repost)\b"),
        ("Comment required", r"\bcomment\b"),
        ("Subscribe required", r"\bsubscribe\b"),
        ("Share required", r"\bshare\b"),
        ("Email required", r"\bemail\b"),
        ("Newsletter signup", r"\bnewsletter\b"),
        ("Register/account required", r"\b(register|registration|create an account|sign up)\b"),
        ("UK residents only", r"\buk residents?\b|\buk only\b|\buk mainland\b"),
        ("18+ requirement", r"\b18\+\b|\bover 18\b|\baged 18\b"),
    ]

    for label, pattern in rule_patterns:

        if re.search(
            pattern,
            lower,
            flags=re.IGNORECASE
        ):
            rules.append(label)

    # CAPTCHA.
    captcha = any(
        word in lower
        for word in CAPTCHA_WORDS
    )

    # Automation restrictions.
    automation_blocked = any(
        phrase in lower
        for phrase in AUTOMATION_BLOCK_WORDS
    )

    return rules, captcha, automation_blocked


# ============================================================
# AUTOMATION DECISION
# ============================================================

def determine_entry_status(
    title,
    description,
    url
):
    """
    Determines whether the application should consider
    automatic entry appropriate.

    This does NOT bypass CAPTCHA or website protections.
    """

    rules, captcha, automation_blocked = extract_rules(
        title,
        description
    )

    domain = urlparse(url).netloc.lower()

    # Social media giveaways should normally be manual.
    is_social = any(
        platform in domain
        for platform in SOCIAL_PLATFORMS
    )

    if captcha:
        return (
            "🚫 DO NOT AUTO-ENTER",
            "CAPTCHA detected",
            rules
        )

    if automation_blocked:
        return (
            "🚫 DO NOT AUTO-ENTER",
            "Giveaway appears to prohibit automation",
            rules
        )

    if is_social:
        return (
            "👤 MANUAL ENTRY",
            "Social-media entry detected",
            rules
        )

    # If no explicit automation prohibition is found,
    # mark it as potentially suitable for automation,
    # but do not claim the site permits bots.
    return (
        "⚠️ REVIEW BEFORE AUTO-ENTRY",
        "No CAPTCHA/prohibition detected; check the official rules",
        rules
    )


# ============================================================
# SEARCH
# ============================================================

def search_query(query):

    for attempt in range(MAX_RETRIES + 1):

        try:

            print(
                f"Searching: {query} "
                f"(attempt {attempt + 1}/{MAX_RETRIES + 1})"
            )

            with DDGS(
                timeout=SEARCH_TIMEOUT
            ) as ddgs:

                raw_results = list(
                    ddgs.text(
                        query,
                        region="uk-en",
                        safesearch="moderate",
                        max_results=MAX_RESULTS_PER_SEARCH
                    )
                )

            giveaways = []

            for result in raw_results:

                title = normalise_text(
                    result.get("title", "")
                )

                description = normalise_text(
                    result.get("body", "")
                )

                url = normalise_text(
                    result.get("href", "")
                )

                if not title or not url:
                    continue

                if not looks_like_giveaway(
                    title,
                    description
                ):
                    continue

                category = get_category(
                    title,
                    description
                )

                value = extract_value(
                    f"{title} {description}"
                )

                entry_status, reason, rules = (
                    determine_entry_status(
                        title,
                        description,
                        url
                    )
                )

                giveaways.append({
                    "title": title,
                    "description": description,
                    "url": url,
                    "source": query,
                    "category": category,
                    "value": value,
                    "rules": rules,
                    "entry_status": entry_status,
                    "entry_reason": reason,
                })

            return giveaways

        except Exception as error:

            print(
                f"Search failed for "
                f"\"{query}\": {error}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(0.5)

    return []


# ============================================================
# REMOVE DUPLICATES
# ============================================================

def clean_results(results):

    unique = {}

    for result in results:

        url = result.get("url", "").strip()

        if not url:
            continue

        # Normalise URL slightly.
        url = url.rstrip("/")

        if url not in unique:
            result["url"] = url
            unique[url] = result

    return list(unique.values())


# ============================================================
# MAIN APPLICATION
# ============================================================

class GiveawayFinder:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "🎁 Free UK Giveaway Finder"
        )

        self.root.geometry(
            "1150x780"
        )

        self.root.minsize(
            900,
            650
        )

        self.seen = load_seen()

        self.results = []

        self.searching = False

        self.create_interface()


    # ========================================================
    # INTERFACE
    # ========================================================

    def create_interface(self):

        # Header
        header = tk.Frame(
            self.root,
            bg="#151515"
        )

        header.pack(
            fill="x"
        )

        tk.Label(
            header,
            text="🎁 FREE GIVEAWAY FINDER",
            font=("Segoe UI", 24, "bold"),
            fg="white",
            bg="#151515"
        ).pack(
            pady=(15, 2)
        )

        tk.Label(
            header,
            text=(
                "🇬🇧 UK Giveaways • Gaming • Tech • Cash • "
                "Travel • Food • Shopping • More"
            ),
            font=("Segoe UI", 11),
            fg="#bbbbbb",
            bg="#151515"
        ).pack(
            pady=(0, 15)
        )


        # Controls
        controls = tk.Frame(
            self.root
        )

        controls.pack(
            fill="x",
            padx=20,
            pady=15
        )


        self.search_button = tk.Button(
            controls,
            text="🔎 SEARCH GIVEAWAYS",
            font=("Segoe UI", 11, "bold"),
            padx=18,
            pady=9,
            command=self.start_search
        )

        self.search_button.pack(
            side="left"
        )


        self.clear_button = tk.Button(
            controls,
            text="🗑 Clear Results",
            font=("Segoe UI", 10),
            padx=14,
            pady=8,
            command=self.clear_results
        )

        self.clear_button.pack(
            side="left",
            padx=8
        )


        self.open_all_button = tk.Button(
            controls,
            text="🌐 Open All",
            font=("Segoe UI", 10),
            padx=14,
            pady=8,
            command=self.open_all
        )

        self.open_all_button.pack(
            side="left"
        )


        self.status = tk.Label(
            controls,
            text="Ready to search",
            font=("Segoe UI", 10)
        )

        self.status.pack(
            side="right"
        )


        # Progress
        self.progress = ttk.Progressbar(
            self.root,
            mode="indeterminate"
        )

        self.progress.pack(
            fill="x",
            padx=20,
            pady=(0, 8)
        )


        # Filter frame
        filter_frame = tk.LabelFrame(
            self.root,
            text="Filters",
            padx=10,
            pady=8
        )

        filter_frame.pack(
            fill="x",
            padx=20,
            pady=(0, 10)
        )


        tk.Label(
            filter_frame,
            text="Category:"
        ).pack(
            side="left"
        )


        self.category_var = tk.StringVar(
            value="All"
        )

        self.category_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.category_var,
            state="readonly",
            width=18,
            values=[
                "All",
                "Gaming",
                "Technology",
                "Money",
                "Travel",
                "Food & Drink",
                "Beauty",
                "Home",
                "Cars",
                "Clothing",
                "Pets",
                "General",
            ]
        )

        self.category_combo.pack(
            side="left",
            padx=5
        )

        self.category_combo.bind(
            "<<ComboboxSelected>>",
            lambda event: self.refresh_display()
        )


        tk.Label(
            filter_frame,
            text="Entry:"
        ).pack(
            side="left",
            padx=(20, 0)
        )


        self.entry_var = tk.StringVar(
            value="All"
        )

        self.entry_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.entry_var,
            state="readonly",
            width=25,
            values=[
                "All",
                "Potentially automatable",
                "Manual entry",
                "Do not auto-enter",
            ]
        )

        self.entry_combo.pack(
            side="left",
            padx=5
        )

        self.entry_combo.bind(
            "<<ComboboxSelected>>",
            lambda event: self.refresh_display()
        )


        self.new_only_var = tk.BooleanVar(
            value=True
        )

        tk.Checkbutton(
            filter_frame,
            text="Only new results",
            variable=self.new_only_var,
            command=self.refresh_display
        ).pack(
            side="left",
            padx=15
        )


        # Results
        results_frame = tk.Frame(
            self.root
        )

        results_frame.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=5
        )


        scrollbar = ttk.Scrollbar(
            results_frame,
            orient="vertical"
        )

        scrollbar.pack(
            side="right",
            fill="y"
        )


        self.results_box = tk.Text(
            results_frame,
            wrap="word",
            font=("Segoe UI", 10),
            padx=15,
            pady=15,
            yscrollcommand=scrollbar.set
        )

        self.results_box.pack(
            fill="both",
            expand=True
        )

        scrollbar.config(
            command=self.results_box.yview
        )


        # Footer
        tk.Label(
            self.root,
            text=(
                "⚠️ Auto-entry never bypasses CAPTCHA, anti-bot "
                "systems or giveaway rules. Always check the official rules."
            ),
            font=("Segoe UI", 9),
            fg="#777777"
        ).pack(
            pady=6
        )


    # ========================================================
    # START SEARCH
    # ========================================================

    def start_search(self):

        if self.searching:
            return

        self.searching = True

        self.search_button.config(
            state="disabled",
            text="🔎 SEARCHING..."
        )

        self.progress.start(10)

        self.results_box.delete(
            "1.0",
            tk.END
        )

        self.status.config(
            text=f"Searching {len(SEARCHES)} searches..."
        )

        threading.Thread(
            target=self.run_search,
            daemon=True
        ).start()


    # ========================================================
    # RUN SEARCH
    # ========================================================

    def run_search(self):

        all_results = []

        completed = 0

        total = len(SEARCHES)


        with ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        ) as executor:

            futures = {
                executor.submit(
                    search_query,
                    query
                ): query

                for query in SEARCHES
            }


            for future in as_completed(
                futures
            ):

                completed += 1

                try:

                    results = future.result()

                    all_results.extend(
                        results
                    )

                except Exception as error:

                    print(
                        f"Worker error: {error}"
                    )


                self.root.after(
                    0,
                    self.update_progress,
                    completed,
                    total
                )


        all_results = clean_results(
            all_results
        )


        # New results only.
        new_results = []

        for result in all_results:

            url = result["url"]

            if url not in self.seen:

                new_results.append(
                    result
                )


        # Mark everything found as seen.
        for result in all_results:
            self.seen.add(
                result["url"]
            )


        save_seen(
            self.seen
        )


        self.results = new_results


        self.root.after(
            0,
            self.display_results
        )


    # ========================================================
    # PROGRESS
    # ========================================================

    def update_progress(
        self,
        completed,
        total
    ):

        self.status.config(
            text=f"Searching... {completed}/{total}"
        )


    # ========================================================
    # FILTERING
    # ========================================================

    def get_filtered_results(self):

        filtered = []

        selected_category = (
            self.category_var.get()
        )

        selected_entry = (
            self.entry_var.get()
        )


        for result in self.results:

            if (
                selected_category != "All"
                and result["category"] != selected_category
            ):
                continue


            if selected_entry == "Potentially automatable":

                if not result["entry_status"].startswith(
                    "⚠️"
                ):
                    continue


            elif selected_entry == "Manual entry":

                if not result["entry_status"].startswith(
                    "👤"
                ):
                    continue


            elif selected_entry == "Do not auto-enter":

                if not result["entry_status"].startswith(
                    "🚫"
                ):
                    continue


            filtered.append(
                result
            )


        return filtered


    # ========================================================
    # DISPLAY
    # ========================================================

    def display_results(self):

        self.progress.stop()

        self.searching = False

        self.search_button.config(
            state="normal",
            text="🔎 SEARCH GIVEAWAYS"
        )


        self.refresh_display()


    def refresh_display(self):

        self.results_box.delete(
            "1.0",
            tk.END
        )


        results = self.get_filtered_results()


        if not results:

            self.results_box.insert(
                tk.END,
                "\n😕 No results match your filters.\n\n"
            )

            if self.results:

                self.status.config(
                    text=(
                        f"{len(self.results)} found, "
                        "but none match the current filters"
                    )
                )

            else:

                self.status.config(
                    text="No new giveaways found"
                )

            return


        self.status.config(
            text=f"🎉 {len(results)} giveaway(s)"
        )


        for number, giveaway in enumerate(
            results,
            start=1
        ):

            self.results_box.insert(
                tk.END,
                "\n"
                + "=" * 90
                + "\n"
            )


            self.results_box.insert(
                tk.END,
                f"🎁 GIVEAWAY #{number}\n\n",
                "heading"
            )


            self.results_box.insert(
                tk.END,
                f"{giveaway['title']}\n",
                "title"
            )


            self.results_box.insert(
                tk.END,
                f"\n📂 Category: {giveaway['category']}\n"
            )


            self.results_box.insert(
                tk.END,
                f"💷 Estimated value: {giveaway['value']}\n"
            )


            self.results_box.insert(
                tk.END,
                "\n📋 RULES / REQUIREMENTS\n",
                "subheading"
            )


            if giveaway["rules"]:

                for rule in giveaway["rules"]:

                    self.results_box.insert(
                        tk.END,
                        f"   • {rule}\n"
                    )

            else:

                self.results_box.insert(
                    tk.END,
                    "   • No obvious requirements detected "
                    "from the search result.\n"
                )


            self.results_box.insert(
                tk.END,
                "\n🤖 ENTRY STATUS\n",
                "subheading"
            )


            self.results_box.insert(
                tk.END,
                f"   {giveaway['entry_status']}\n"
            )


            self.results_box.insert(
                tk.END,
                f"   Reason: {giveaway['entry_reason']}\n"
            )


            self.results_box.insert(
                tk.END,
                "\n📝 DESCRIPTION\n",
                "subheading"
            )


            self.results_box.insert(
                tk.END,
                f"{giveaway['description']}\n\n"
            )


            self.results_box.insert(
                tk.END,
                "🔗 OPEN GIVEAWAY\n",
                "subheading"
            )


            start_index = self.results_box.index(
                tk.END
            )

            self.results_box.insert(
                tk.END,
                giveaway["url"] + "\n",
                "link"
            )


            end_index = self.results_box.index(
                tk.END
            )


            # Store URL against the link range.
            self.results_box.tag_add(
                f"url_{number}",
                start_index,
                end_index
            )

            self.results_box.tag_bind(
                f"url_{number}",
                "<Button-1>",
                lambda event,
                url=giveaway["url"]:
                webbrowser.open(url)
            )


            self.results_box.insert(
                tk.END,
                f"\n🔎 Search: {giveaway['source']}\n"
            )


        # Text styling.
        self.results_box.tag_config(
            "heading",
            font=("Segoe UI", 14, "bold")
        )

        self.results_box.tag_config(
            "title",
            font=("Segoe UI", 12, "bold")
        )

        self.results_box.tag_config(
            "subheading",
            font=("Segoe UI", 10, "bold")
        )

        self.results_box.tag_config(
            "link",
            foreground="blue",
            underline=True
        )


    # ========================================================
    # OPEN ALL
    # ========================================================

    def open_all(self):

        results = self.get_filtered_results()

        if not results:

            messagebox.showinfo(
                "No results",
                "There are no giveaways currently displayed."
            )

            return


        answer = messagebox.askyesno(
            "Open giveaways",
            (
                f"Open {len(results)} giveaway pages "
                "in your browser?"
            )
        )


        if not answer:
            return


        for result in results:

            try:

                webbrowser.open(
                    result["url"]
                )

                time.sleep(0.3)

            except Exception:
                pass


    # ========================================================
    # CLEAR RESULTS
    # ========================================================

    def clear_results(self):

        self.results = []

        self.results_box.delete(
            "1.0",
            tk.END
        )

        self.status.config(
            text="Results cleared"
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    root = tk.Tk()

    app = GiveawayFinder(
        root
    )

    root.mainloop()