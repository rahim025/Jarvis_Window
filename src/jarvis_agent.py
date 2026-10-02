import os
import json
import time
import logging
from pathlib import Path

try:
    import google.genai as genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

logging.basicConfig(level=logging.INFO, format="[JARVIS_AGENT] %(message)s")


class JarvisAgent:
    """Agent minimal réutilisable (mémoire persistante + Gemini)."""

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash",
                 memory_file: str = "jarvis_memoire.json"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model
        self.memory_file = Path(memory_file)
        self.client = genai.Client(api_key=self.api_key) if (genai and self.api_key) else None
        self.memory = self._load_memory()

    def _load_memory(self) -> dict:
        if self.memory_file.exists():
            try:
                return json.loads(self.memory_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logging.warning("Mémoire illisible : %s", exc)
        return {}

    def _save_memory(self) -> None:
        try:
            self.memory_file.write_text(json.dumps(self.memory, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logging.warning("Mémoire non sauvegardée : %s", exc)

    def remember(self, key: str, value: str) -> None:
        self.memory[key] = {"valeur": value, "timestamp": time.strftime("%d/%m/%Y %H:%M")}
        self._save_memory()

    def forget(self, key: str) -> bool:
        if key in self.memory:
            del self.memory[key]
            self._save_memory()
            return True
        return False

    def memory_context(self) -> str:
        if not self.memory:
            return ""
        lignes = ["MEMOIRE PERSISTANTE :"]
        for cle, data in self.memory.items():
            lignes.append(f"  - {cle} : {data['valeur']} (noté le {data['timestamp']})")
        return "\n".join(lignes)

    def system_prompt(self) -> str:
        return ("Tu es JARVIS, assistant IA personnel créé par Rahim Batchabi.\n"
                "Réponses courtes, ton sarcastique mais respectueux.\n\n" + self.memory_context())

    def generate_response(self, user_message: str) -> str:
        if not self.client:
            raise RuntimeError("google-genai absent ou GEMINI_API_KEY manquante.")
        reponse = self.client.models.generate_content(
            model=self.model,
            contents=user_message,
            config=types.GenerateContentConfig(system_instruction=self.system_prompt()),
        )
        return (reponse.text or "").strip()


def main() -> None:
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description="Agent JARVIS minimal.")
    parser.add_argument("message", nargs="+")
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--memory-file", default="jarvis_memoire.json")
    args = parser.parse_args()
    agent = JarvisAgent(model=args.model, memory_file=args.memory_file)
    try:
        print(agent.generate_response(" ".join(args.message)))
    except Exception as exc:
        logging.error("Impossible de générer une réponse : %s", exc)


if __name__ == "__main__":
    main()
