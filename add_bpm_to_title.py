import os
import math
import struct
import wave
import re
import urllib.request
import urllib.parse
import sys
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
import librosa
import numpy as np

# Ensure stdout handles UTF-8 for printing special characters like sharp/flat signs on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def normalize_string(s: str) -> str:
    """
    Cleans up a string for metadata matching: converts to lowercase,
    removes common featured artist markers/conjunctions, removes punctuation,
    and collapses multiple spaces.
    """
    s = s.lower()
    # Remove common featured artist markers and conjunctions
    s = re.sub(r'\b(feat|ft|feat\.|and|with|&|vs|vs\.)\b', ' ', s)
    # Remove non-alphanumeric characters
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    # Collapse multiple spaces and strip
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def words_set(s: str) -> set[str]:
    return set(normalize_string(s).split())

def is_metadata_match(target_artist: str, target_title: str, result_artist: str, result_title: str) -> bool:
    """
    Checks if the search result matches the target track based on word overlap.
    """
    target_art_words = words_set(target_artist)
    target_tit_words = words_set(target_title)
    
    result_art_words = words_set(result_artist)
    result_tit_words = words_set(result_title)
    
    # Check title overlap
    title_overlap = len(target_tit_words.intersection(result_tit_words))
    title_matched = False
    if title_overlap > 0:
        min_len = min(len(target_tit_words), len(result_tit_words))
        if min_len > 0 and title_overlap / min_len >= 0.7:
            title_matched = True
            
    # Check artist overlap
    artist_overlap = len(target_art_words.intersection(result_art_words))
    artist_matched = False
    if artist_overlap > 0:
        artist_matched = True
        
    # Special case: if target artist is empty, rely on title match only
    if not target_art_words:
        return title_matched
        
    return artist_matched and title_matched

def estimate_bpm_with_dj_website(filepath: str) -> float | None:
    """
    Estimates the BPM of an audio file using songbpm.com.
    Falls back to parsing the filename if ID3 tags are missing.
    Returns None if estimation fails.
    """
    filename = os.path.basename(filepath)
    try:
        # Load ID3 tags to get artist and title
        audio = EasyID3(filepath)
        artist = audio.get('artist', [''])[0]
        title = audio.get('title', [''])[0]
    except Exception:
        artist, title = '', ''
        
    # If ID3 tags are missing, parse from filename
    if not title:
        name_without_ext = os.path.splitext(filename)[0]
        # Clean up any existing BPM markers in filename (e.g. "Song (120 BPM)")
        name_cleaned = re.sub(r"\s*\(\d+\s*BPM\)", "", name_without_ext, flags=re.IGNORECASE).strip()
        # Clean up any leading BPM prefix from filename (e.g. "182 El Timba - Hermano")
        name_cleaned = re.sub(r"^\d{2,3}\s+", "", name_cleaned)
        
        if " - " in name_cleaned:
            parts = name_cleaned.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()
        else:
            title = name_cleaned
            
    # Clean tags for querying
    artist_clean = re.sub(r"\s*\(\d+\s*BPM\)", "", artist, flags=re.IGNORECASE).strip()
    artist_clean = re.sub(r"^\d{2,3}\s+", "", artist_clean)
    
    title_clean = re.sub(r"\s*\(\d+\s*BPM\)", "", title, flags=re.IGNORECASE).strip()
    title_clean = re.sub(r"^\d{2,3}\s+", "", title_clean)
    
    # If both empty, cannot search
    if not title_clean:
        print(f"Could not extract a valid search query for {filename}")
        return None
        
    # Build query
    query = f"{artist_clean} {title_clean}".strip()
    print(f"Querying songbpm.com for '{query}'...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://songbpm.com',
        'Referer': 'https://songbpm.com/',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    try:
        url = "https://songbpm.com/searches"
        data = urllib.parse.urlencode({'query': query}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
        # Parse song cards
        cards = html.split('<a class="hover:bg-foreground/5')
        candidates = []
        
        for card in cards[1:]:
            # Extract artist
            artist_match = re.search(r'<p class="text-sm font-light uppercase[^"]*">\s*([^<]+?)\s*</p>', card)
            res_artist = artist_match.group(1).strip() if artist_match else "Unknown Artist"
            
            # Extract title
            title_match = re.search(r'<p class="pr-2 text-lg[^"]*">\s*([^<]+?)\s*</p>', card)
            res_title = title_match.group(1).strip() if title_match else "Unknown Title"
            
            # Extract BPM
            bpm_match = re.search(r'<span class="text-xs uppercase">BPM</span>\s*<span class="text-nowrap text-2xl font-bold sm:text-3xl sm:font-normal">\s*(\d+)\s*</span>', card)
            res_bpm = int(bpm_match.group(1).strip()) if bpm_match else None
            
            # Extract Key (optional)
            key_match = re.search(r'<span class="text-xs uppercase">Key</span>\s*<span class="text-nowrap text-2xl sm:text-3xl">\s*([^<]+?)\s*</span>', card)
            res_key = key_match.group(1).strip() if key_match else None
            
            if res_bpm:
                candidates.append({
                    'artist': res_artist,
                    'title': res_title,
                    'bpm': res_bpm,
                    'key': res_key
                })
                
        # Find best match
        for candidate in candidates:
            cand_artist = urllib.parse.unquote(candidate['artist']).replace('&#39;', "'").replace('&amp;', '&')
            cand_title = urllib.parse.unquote(candidate['title']).replace('&#39;', "'").replace('&amp;', '&')
            
            if is_metadata_match(artist_clean, title_clean, cand_artist, cand_title):
                print(f"Found match: '{cand_artist}' - '{cand_title}' | BPM: {candidate['bpm']} | Key: {candidate['key']}")
                return float(candidate['bpm'])
                
        print(f"No matching track found on songbpm.com for '{query}' out of {len(candidates)} search results.")
        return None
    except Exception as e:
        print(f"Error querying songbpm.com for '{query}': {e}")
        return None


def estimate_bpm_with_librosa(filepath: str) -> float | None:
    """
    Estimates the BPM of an audio file using librosa.
    Returns None if estimation fails.
    """
    try:
        # librosa.load returns audio as mono by default, sr=None preserves native sample rate
        y, sr = librosa.load(filepath, sr=None, mono=True)
        # librosa.beat.tempo returns an array, first element is the global tempo estimate
        tempo = librosa.feature.tempo(y=y, sr=sr, start_bpm=150, max_tempo=210, aggregate=None)
        # Convert tempo to a scalar float robustly
        if isinstance(tempo, np.ndarray):
            tempo_val = float(tempo[0]) if tempo.size > 0 else 0.0
        else:
            tempo_val = float(tempo)

        if tempo_val > 0:
            return tempo_val
        else:
            return None
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error estimating BPM with librosa for {os.path.basename(filepath)}: {e}")
        return None

def normalize_filename(filename: str) -> str:
    # Remove extension
    name, _ = os.path.splitext(filename)
    name = name.lower()
    # Remove leading BPM prefix (e.g. "120 ")
    name = re.sub(r"^\d{2,3}\s+", "", name)
    # Remove trailing BPM suffix (e.g. " (120 bpm)" or " (120bpm)")
    name = re.sub(r"\s*\(\d+\s*bpm\)", "", name)
    # Collapse multiple spaces and strip
    name = re.sub(r"\s+", " ", name).strip()
    return name

def append_bpm_to_title(source_directory: str, target_directory: str = None):
    if not os.path.exists(source_directory):
        print(f"Source folder '{source_directory}' does not exist.")
        return
    
    # Load target files to avoid copying duplicates
    target_files = set()
    if target_directory:
        if os.path.exists(target_directory):
            for f in os.listdir(target_directory):
                if f.lower().endswith(".mp3"):
                    target_files.add(normalize_filename(f))
        else:
            print(f"Target folder '{target_directory}' does not exist. Creating it.")
            os.makedirs(target_directory, exist_ok=True)

    files = [f for f in os.listdir(source_directory) if f.lower().endswith(".mp3")]
    if not files:
        print(f"No MP3 files found in folder '{source_directory}'.")
        return

    import shutil

    for filename in files:
        filepath = os.path.join(source_directory, filename)
        
        # Check if already in target directory
        norm_name = normalize_filename(filename)
        if target_directory and norm_name in target_files:
            print(f"File: '{filename}' -> Already exists in target folder. Skipping.")
            continue

        try:
            # Load existing ID3 tags
            audio = EasyID3(filepath)

            # Check if Title tag exists
            has_title = 'title' in audio
            original_title = audio['title'][0] if has_title else os.path.splitext(filename)[0]

            # Check if title already contains a BPM marker
            bpm_match = re.search(r"\b(\d+)\s*bpm\b", original_title, re.IGNORECASE)
            has_bpm_in_title = bool(bpm_match)

            if has_bpm_in_title:
                bpm_rounded = int(bpm_match.group(1))
                print(f"File: '{filename}' -> Title already contains BPM: '{original_title}'. Using existing BPM: {bpm_rounded}.")
                
                # Copy the file to the target directory if specified
                if target_directory:
                    clean_filename = re.sub(r"^\d{2,3}\s+", "", filename)
                    target_filename = f"{bpm_rounded} {clean_filename}"
                    target_filepath = os.path.join(target_directory, target_filename)
                    try:
                        shutil.copy2(filepath, target_filepath)
                        print(f"Copied file to target: '{target_filename}'")
                        
                        # Set ID3 BPM tag on the target file
                        target_audio = EasyID3(target_filepath)
                        if target_audio.get('bpm', [''])[0] != str(bpm_rounded):
                            target_audio['bpm'] = str(bpm_rounded)
                            target_audio.save()
                            print(f"Set target file ID3 BPM tag to: {bpm_rounded}")
                    except Exception as copy_err:
                        print(f"Error copying '{target_filename}' to target: {copy_err}")
                else:
                    # In-place: set ID3 BPM tag on source file
                    if audio.get('bpm', [''])[0] != str(bpm_rounded):
                        audio['bpm'] = str(bpm_rounded)
                        audio.save()
                        print(f"Set ID3 BPM tag to: {bpm_rounded}")
                    
                    # In-place: rename source file
                    clean_filename = re.sub(r"^\d{2,3}\s+", "", filename)
                    new_filename = f"{bpm_rounded} {clean_filename}"
                    new_filepath = os.path.join(source_directory, new_filename)
                    if filepath != new_filepath:
                        try:
                            os.rename(filepath, new_filepath)
                            print(f"Renamed file: '{filename}' -> '{new_filename}'")
                        except Exception as rename_err:
                            print(f"Error renaming file: {rename_err}")
                continue

            # Estimate BPM
            print(f"\nEstimating BPM for '{filename}'...")
            bpm = estimate_bpm_with_dj_website(filepath)
            if bpm is None:
                print(f"DJ website lookup failed. Falling back to librosa local analysis...")
                bpm = estimate_bpm_with_librosa(filepath)
            if bpm is None or bpm <= 0.0:
                print(f"Could not estimate BPM for {filename}. Skipping tagging.")
                if target_directory:
                    target_filepath = os.path.join(target_directory, filename)
                    try:
                        shutil.copy2(filepath, target_filepath)
                        print(f"Copied file (untagged) to target: '{filename}'")
                    except Exception as copy_err:
                        print(f"Error copying '{filename}' to target: {copy_err}")
                continue

            # Intelligently double half-time BPMs (typically < 120 for Latin/Salsa music)
            if bpm < 120.0:
                old_bpm = bpm
                bpm = bpm * 2.0
                print(f"Detected half-time BPM ({old_bpm:.1f}). Doubled to full-time ({bpm:.1f}).")

            bpm_rounded = round(bpm)
            
            clean_filename = re.sub(r"^\d{2,3}\s+", "", filename)
            new_filename = f"{bpm_rounded} {clean_filename}"

            if target_directory:
                target_filepath = os.path.join(target_directory, new_filename)
                try:
                    shutil.copy2(filepath, target_filepath)
                    print(f"Copied file to target: '{new_filename}'")
                    
                    # Update tags in the TARGET file only
                    target_audio = EasyID3(target_filepath)
                    target_audio['bpm'] = str(bpm_rounded)
                    
                    original_title_cleaned = re.sub(r"\s*\(\d+\s*BPM\)", "", original_title, flags=re.IGNORECASE).strip()
                    bpms_suffix = f" ({bpm_rounded} BPM)"
                    new_title = f"{original_title_cleaned}{bpms_suffix}"
                    target_audio['title'] = [new_title]
                    
                    target_audio.save()
                    print(f"Set target file Title: '{new_title}' | Tagged BPM: {bpm_rounded}")
                except Exception as copy_err:
                    print(f"Error copying/tagging target file '{new_filename}': {copy_err}")
            else:
                # In-place update of source file
                audio['bpm'] = str(bpm_rounded)
                original_title_cleaned = re.sub(r"\s*\(\d+\s*BPM\)", "", original_title, flags=re.IGNORECASE).strip()
                bpms_suffix = f" ({bpm_rounded} BPM)"
                new_title = f"{original_title_cleaned}{bpms_suffix}"
                audio['title'] = [new_title]
                audio.save()
                
                new_filepath = os.path.join(source_directory, new_filename)
                if filepath != new_filepath:
                    try:
                        os.rename(filepath, new_filepath)
                        print(f"Renamed file: '{filename}' -> '{new_filename}'")
                    except Exception as rename_err:
                        print(f"Error renaming file: {rename_err}")
        except Exception as e:
            print(f"Error processing {filename}: {e}")

def generate_test_audio(filepath: str, target_bpm: int = 120, duration_seconds: int = 5, sample_rate: int = 44100):
    """
    Generates a synthetic mono WAV file with periodic metronome pulses
    to test the BPM estimation logic.
    """
    print(f"Generating synthetic test audio file '{filepath}' with exactly {target_bpm} BPM...")
    with wave.open(filepath, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2) # 16-bit
        wav.setframerate(sample_rate)
        
        # Calculate samples per beat
        beat_interval_samples = int(sample_rate * (60.0 / target_bpm))
        # Keep pulse short (e.g., 50ms) to simulate a drum hit / click
        pulse_duration_samples = int(sample_rate * 0.05)
        
        total_samples = sample_rate * duration_seconds
        for sample_idx in range(total_samples):
            # Check where we are inside the beat cycle
            pos_in_beat = sample_idx % beat_interval_samples
            if pos_in_beat < pulse_duration_samples:
                # 440 Hz Sine wave with rapid linear decay
                t = pos_in_beat / sample_rate
                decay_factor = 1.0 - (pos_in_beat / pulse_duration_samples)
                val = int(16384 * math.sin(2 * math.pi * 440 * t) * decay_factor)
            else:
                val = 0
            wav.writeframes(struct.pack('<h', val))

def debug_try_and_print_bpm():
    """
    Debug helper: creates a synthetic test song/audio file, runs
    our BPM estimation on it, and prints the results.
    """

    test_filepath = os.path.join(os.path.dirname(__file__), "debug_test_song_120bpm.wav")
    target_bpm = 120
    
    try:
        generate_test_audio(test_filepath, target_bpm=target_bpm, duration_seconds=6)
        
        print("\n--- Running BPM Estimation Test ---")
        estimated_bpm = estimate_bpm_with_librosa(test_filepath)
        if estimated_bpm is not None:
            print(f"Target/Synthetic BPM of song: {target_bpm}")
            print(f"Estimated BPM of song       : {estimated_bpm:.2f}")
        else:
            print("Failed to estimate BPM on synthetic song.")
        print("-----------------------------------\n")
    finally:
        # Clean up temporary file
        if os.path.exists(test_filepath):
            try:
                os.remove(test_filepath)
            except Exception as e:
                print(f"Warning: Could not remove temporary test file '{test_filepath}': {e}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Estimate and append BPM to the title and filename of MP3 files in a directory."
    )
    parser.add_argument(
        "source_folder",
        help="Folder containing the MP3 files to analyse."
    )
    parser.add_argument(
        "target_folder",
        nargs="?",
        default=None,
        help="Optional folder to copy BPM-prefixed copies into. "
             "Omit this to tag the files in place instead."
    )
    
    args = parser.parse_args()
    source_folder = args.source_folder
    target_folder = args.target_folder

    # Process specified folder if it exists
    if os.path.exists(source_folder):
        append_bpm_to_title(source_folder, target_folder)
    else:
        print(f"Error: Source folder '{source_folder}' does not exist.")
