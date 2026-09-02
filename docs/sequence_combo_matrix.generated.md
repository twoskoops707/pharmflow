# Sequence Combo Matrix (Generated)

This file is machine-generated from current code-defined options.

```json
{
  "generated_at_utc": "2026-05-06T05:43:02Z",
  "scope": "Home-screen combinations supported by wizard/dashboard sequence selection",
  "combo_family": "home_combo_v2",
  "combo_count": 108,
  "dimensions": [
    "entry",
    "footer",
    "hero",
    "bottom",
    "timer"
  ],
  "dimension_value_counts": {
    "entry": 2,
    "footer": 3,
    "hero": 2,
    "bottom": 3,
    "timer": 3
  },
  "choice_dimensions": {
    "entry": [
      {
        "value": "direct",
        "label": "Direct getdabflow landing",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS"
      },
      {
        "value": "google_home",
        "label": "Google homepage search then result",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS"
      }
    ],
    "footer": [
      {
        "value": "left",
        "label": "Left footer anchor",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS"
      },
      {
        "value": "center",
        "label": "Center footer anchor",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS"
      },
      {
        "value": "right",
        "label": "Right footer anchor",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS"
      }
    ],
    "hero": [
      {
        "value": "off",
        "label": "No extra hero-top retap",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS"
      },
      {
        "value": "on",
        "label": "Include hero-top retap",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS"
      }
    ],
    "bottom": [
      {
        "value": "center",
        "label": "Center bottom strip tap",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS"
      },
      {
        "value": "right",
        "label": "Right bottom strip tap",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS"
      },
      {
        "value": "left",
        "label": "Left bottom strip tap",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS"
      }
    ],
    "timer": [
      {
        "value": "none",
        "label": "No long timer block",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      {
        "value": "single96",
        "label": "Single 96s timer then BACK",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      {
        "value": "stacked",
        "label": "Stacked 96+102+88 timer block",
        "source_symbol": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      }
    ]
  },
  "selection_behavior": {
    "playlist_selection": {
      "playlist_mode": {
        "ordered": "Round-robin pick one file per set each iteration (set A then set B).",
        "random": "Deterministically random pick one file per set each iteration.",
        "series": "Run every file in set A then every file in set B each iteration."
      },
      "playlist_shuffle": {
        "none": "No pre-mode reordering.",
        "set_a": "Shuffle set A only before mode logic.",
        "set_b": "Shuffle set B only before mode logic.",
        "both_sets_separately": "Shuffle A and B independently before mode logic.",
        "combined": "Merge A+B, shuffle merged list, treat as single set A."
      },
      "secondary_set": "Optional set B; when present, behavior depends on mode and always runs after set A context."
    },
    "source_symbols": {
      "playlist_mode": "automation/sequence_playlist.py::resolve_steps / pick_rotating_filename",
      "playlist_shuffle": "automation/sequence_playlist.py::SHUFFLE_MODES / _apply_playlist_shuffle",
      "wizard_shuffle_validation": "wizard/setup_wizard.py::_normalize_sequence_playlist_shuffle",
      "wizard_playlist_ui": "wizard/setup_wizard.py::PerPhoneSequenceEditor.__init__ (playlist controls)",
      "dashboard_runtime": "automation/dashboard.py::_phone_steps_for_run -> resolve_steps"
    }
  },
  "matrix": [
    {
      "combo_id": "home_combo_v2:direct:left:off:center:none",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "off",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-off_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:off:center:single96",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "off",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-off_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:off:center:stacked",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "off",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-off_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:off:right:none",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "off",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-off_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:off:right:single96",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "off",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-off_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:off:right:stacked",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "off",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-off_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:off:left:none",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "off",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-off_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:off:left:single96",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "off",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-off_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:off:left:stacked",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "off",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-off_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:on:center:none",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "on",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-on_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:on:center:single96",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "on",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-on_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:on:center:stacked",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "on",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-on_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:on:right:none",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "on",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-on_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:on:right:single96",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "on",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-on_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:on:right:stacked",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "on",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-on_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:on:left:none",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "on",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-on_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:on:left:single96",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "on",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-on_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:left:on:left:stacked",
      "choices": {
        "entry": "direct",
        "footer": "left",
        "hero": "on",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-left_hero-on_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:off:center:none",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "off",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-off_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:off:center:single96",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "off",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-off_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:off:center:stacked",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "off",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-off_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:off:right:none",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "off",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-off_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:off:right:single96",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "off",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-off_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:off:right:stacked",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "off",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-off_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:off:left:none",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "off",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-off_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:off:left:single96",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "off",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-off_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:off:left:stacked",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "off",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-off_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:on:center:none",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "on",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-on_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:on:center:single96",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "on",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-on_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:on:center:stacked",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "on",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-on_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:on:right:none",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "on",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-on_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:on:right:single96",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "on",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-on_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:on:right:stacked",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "on",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-on_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:on:left:none",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "on",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-on_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:on:left:single96",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "on",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-on_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:center:on:left:stacked",
      "choices": {
        "entry": "direct",
        "footer": "center",
        "hero": "on",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-center_hero-on_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:off:center:none",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "off",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-off_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:off:center:single96",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "off",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-off_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:off:center:stacked",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "off",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-off_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:off:right:none",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "off",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-off_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:off:right:single96",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "off",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-off_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:off:right:stacked",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "off",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-off_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:off:left:none",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "off",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-off_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:off:left:single96",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "off",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-off_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:off:left:stacked",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "off",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-off_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:on:center:none",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "on",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-on_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:on:center:single96",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "on",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-on_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:on:center:stacked",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "on",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-on_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:on:right:none",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "on",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-on_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:on:right:single96",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "on",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-on_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:on:right:stacked",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "on",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-on_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:on:left:none",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "on",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-on_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:on:left:single96",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "on",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-on_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:direct:right:on:left:stacked",
      "choices": {
        "entry": "direct",
        "footer": "right",
        "hero": "on",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Direct getdabflow landing",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-direct_footer-right_hero-on_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:off:center:none",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "off",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-off_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:off:center:single96",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "off",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-off_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:off:center:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "off",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-off_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:off:right:none",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "off",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-off_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:off:right:single96",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "off",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-off_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:off:right:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "off",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-off_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:off:left:none",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "off",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-off_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:off:left:single96",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "off",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-off_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:off:left:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "off",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-off_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:on:center:none",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "on",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:on:center:single96",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "on",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:on:center:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "on",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:on:right:none",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "on",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:on:right:single96",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "on",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:on:right:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "on",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:on:left:none",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "on",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:on:left:single96",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "on",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:left:on:left:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "left",
        "hero": "on",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Left footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-left_hero-on_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:off:center:none",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "off",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-off_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:off:center:single96",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "off",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-off_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:off:center:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "off",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-off_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:off:right:none",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "off",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-off_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:off:right:single96",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "off",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-off_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:off:right:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "off",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-off_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:off:left:none",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "off",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-off_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:off:left:single96",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "off",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-off_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:off:left:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "off",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-off_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:on:center:none",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "on",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-on_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:on:center:single96",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "on",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-on_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:on:center:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "on",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-on_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:on:right:none",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "on",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-on_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:on:right:single96",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "on",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-on_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:on:right:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "on",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-on_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:on:left:none",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "on",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-on_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:on:left:single96",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "on",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-on_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:center:on:left:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "center",
        "hero": "on",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Center footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-center_hero-on_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:off:center:none",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "off",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-off_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:off:center:single96",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "off",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-off_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:off:center:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "off",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-off_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:off:right:none",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "off",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-off_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:off:right:single96",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "off",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-off_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:off:right:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "off",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-off_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:off:left:none",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "off",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-off_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:off:left:single96",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "off",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-off_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:off:left:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "off",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "No extra hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-off_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:on:center:none",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "on",
        "bottom": "center",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-on_bottom-center_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:on:center:single96",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "on",
        "bottom": "center",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-on_bottom-center_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:on:center:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "on",
        "bottom": "center",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Center bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-on_bottom-center_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:on:right:none",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "on",
        "bottom": "right",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-on_bottom-right_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:on:right:single96",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "on",
        "bottom": "right",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-on_bottom-right_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:on:right:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "on",
        "bottom": "right",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Right bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-on_bottom-right_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:on:left:none",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "on",
        "bottom": "left",
        "timer": "none"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "No long timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-on_bottom-left_timer-none.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:on:left:single96",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "on",
        "bottom": "left",
        "timer": "single96"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Single 96s timer then BACK",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-on_bottom-left_timer-single96.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    },
    {
      "combo_id": "home_combo_v2:google_home:right:on:left:stacked",
      "choices": {
        "entry": "google_home",
        "footer": "right",
        "hero": "on",
        "bottom": "left",
        "timer": "stacked"
      },
      "implied_behavior": {
        "entry": "Google homepage search then result",
        "footer": "Right footer anchor",
        "hero": "Include hero-top retap",
        "bottom": "Left bottom strip tap",
        "timer": "Stacked 96+102+88 timer block",
        "execution_pipeline": "entry block -> home block -> timer lead-in -> timer block -> identity tail (rotate_identity + full_reset)"
      },
      "sequence_filename": "sequence_home_combo_v2_entry-google_home_footer-right_hero-on_bottom-left_timer-stacked.json",
      "choice_sources": {
        "entry": "automation/recordings/sequences/generate_home_combo_sequences.py::ENTRY_OPTIONS",
        "footer": "automation/recordings/sequences/generate_home_combo_sequences.py::FOOTER_OPTIONS",
        "hero": "automation/recordings/sequences/generate_home_combo_sequences.py::HERO_OPTIONS",
        "bottom": "automation/recordings/sequences/generate_home_combo_sequences.py::BOTTOM_OPTIONS",
        "timer": "automation/recordings/sequences/generate_home_combo_sequences.py::TIMER_OPTIONS"
      },
      "definition_symbols": [
        "automation/recordings/sequences/generate_home_combo_sequences.py::build_sequence",
        "automation/recordings/sequences/generate_home_combo_sequences.py::filename_for_combo"
      ]
    }
  ]
}
```
