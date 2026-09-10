"""
Niche classifier — keyword-based, zero API cost.
Κατηγοριοποιεί creators από bio, description και tags.
"""

NICHE_KEYWORDS: dict[str, list[str]] = {
    "Gaming": [
        "gaming", "gamer", "game", "gameplay", "esports", "streamer", "twitch",
        "minecraft", "fortnite", "valorant", "fps", "rpg", "mmorpg", "speedrun",
        "let's play", "lets play", "playthrough", "nintendo", "playstation", "xbox",
        "pc gaming", "mobile gaming", "indie game", "retro gaming",
    ],
    "Fitness": [
        "fitness", "workout", "gym", "health", "exercise", "bodybuilding", "crossfit",
        "weightlifting", "running", "yoga", "pilates", "nutrition", "diet", "protein",
        "muscle", "cardio", "athlete", "personal trainer", "calisthenics", "hiit",
    ],
    "Tech": [
        "tech", "technology", "coding", "programming", "software", "developer",
        "computer", "python", "javascript", "ai", "machine learning", "cybersecurity",
        "gadgets", "reviews", "unboxing", "apple", "android", "linux", "open source",
        "startup", "saas", "cloud", "devops", "data science",
    ],
    "Beauty": [
        "beauty", "makeup", "skincare", "cosmetics", "tutorial", "glam", "foundation",
        "lipstick", "eyeshadow", "contouring", "skincare routine", "haul", "drugstore",
        "luxury beauty", "organic beauty", "self care", "nails", "hair care",
    ],
    "Food": [
        "food", "cooking", "recipe", "chef", "kitchen", "baking", "foodie",
        "restaurant", "vegan", "vegetarian", "keto", "meal prep", "street food",
        "cuisine", "bbq", "grilling", "dessert", "pastry", "nutrition",
    ],
    "Travel": [
        "travel", "vlog", "adventure", "explore", "wanderlust", "backpacking",
        "digital nomad", "vacation", "trip", "destination", "tourism", "hotel",
        "budget travel", "luxury travel", "solo travel", "travel tips",
    ],
    "Finance": [
        "finance", "investing", "money", "stocks", "crypto", "bitcoin", "trading",
        "personal finance", "savings", "budget", "financial freedom", "passive income",
        "real estate", "forex", "options", "dividends", "wealth", "fire movement",
    ],
    "Education": [
        "education", "learn", "tutorial", "how to", "howto", "course", "study",
        "science", "math", "history", "language", "english", "teacher", "professor",
        "knowledge", "skill", "university", "explainer", "documentary",
    ],
    "Fashion": [
        "fashion", "style", "outfit", "clothing", "streetwear", "luxury", "ootd",
        "trend", "designer", "thrift", "sustainable fashion", "accessories", "shoes",
        "mens fashion", "womens fashion", "lookbook", "haul",
    ],
    "Music": [
        "music", "singer", "musician", "band", "producer", "rap", "hip hop",
        "pop", "rock", "edm", "classical", "guitar", "piano", "drums", "bass",
        "songwriter", "cover", "original music", "beats", "mixing", "dj",
    ],
    "Art & Design": [
        "art", "drawing", "illustration", "design", "creative", "artist", "painting",
        "sketch", "digital art", "graphic design", "animation", "3d", "photoshop",
        "procreate", "calligraphy", "photography", "portrait", "concept art",
    ],
    "Comedy": [
        "comedy", "funny", "humor", "memes", "jokes", "stand up", "sketch",
        "parody", "satire", "prank", "roast", "reaction", "skit",
    ],
    "Lifestyle": [
        "lifestyle", "daily", "life", "routine", "morning routine", "productivity",
        "minimalism", "motivation", "self improvement", "mindset", "wellness",
        "mental health", "journaling", "manifestation", "habits",
    ],
    "Parenting": [
        "parenting", "mom", "dad", "family", "kids", "children", "baby", "toddler",
        "pregnancy", "motherhood", "fatherhood", "homeschool", "toy review",
    ],
    "DIY & Crafts": [
        "diy", "crafts", "handmade", "woodworking", "home improvement", "renovation",
        "sewing", "knitting", "crochet", "origami", "upcycle", "maker",
    ],
    "Sports": [
        "sports", "football", "basketball", "soccer", "tennis", "cricket", "golf",
        "swimming", "cycling", "boxing", "mma", "ufc", "athlete", "training",
    ],
    "Pets & Animals": [
        "pets", "dog", "cat", "animals", "wildlife", "animal rescue", "aquarium",
        "reptile", "bird", "hamster", "vet", "pet care", "puppy", "kitten",
    ],
    "Business": [
        "business", "entrepreneur", "startup", "marketing", "e-commerce", "dropshipping",
        "amazon fba", "side hustle", "freelance", "consulting", "leadership",
    ],
}


def classify_niche(text: str) -> tuple[str, list[str]]:
    """
    Επιστρέφει (primary_niche, [all_matching_niches]).
    Δουλεύει με lowercase keyword matching — χωρίς API.
    """
    if not text:
        return "Other", ["Other"]

    text_lower = text.lower()
    scores: dict[str, int] = {}

    for niche, keywords in NICHE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits > 0:
            scores[niche] = hits

    if not scores:
        return "Other", ["Other"]

    # Ταξινόμηση κατά score
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = ranked[0][0]
    all_niches = [n for n, _ in ranked[:3]]  # top-3 niches
    return primary, all_niches


def extract_email(text: str) -> str | None:
    """Βρίσκει email μέσα σε bio/description."""
    import re
    if not text:
        return None
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    match = re.search(pattern, text)
    return match.group(0) if match else None
