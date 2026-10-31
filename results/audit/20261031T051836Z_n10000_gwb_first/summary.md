# Audit n10000_gwb_first seed=0

- **flights**: 10000
- **status_quo_unsafe**: {'pct': 5.1, 'ci95': (4.7, 5.6), 'n': 10000}
- **status_quo_unsafe_by_rule**: {'gate_available': {'pct': 2.6, 'ci95': (2.3, 3.0), 'n': 10000}, 'flight_crew_duty': {'pct': 2.5, 'ci95': (2.2, 2.9), 'n': 10000}, 'final_reserve_fuel': {'pct': 0.1, 'ci95': (0.0, 0.1), 'n': 10000}, 'airport_curfew': {'pct': 0.0, 'ci95': (0.0, 0.1), 'n': 10000}}
- **status_quo_unsafe_by_cause**: {'LATE_AIRCRAFT': {'pct': 5.3, 'ci95': (4.8, 5.8), 'n': 8850}, 'WEATHER': {'pct': 4.2, 'ci95': (3.2, 5.5), 'n': 1150}}
- **status_quo_unsafe_by_delay_source**: {'proxy_LATE_AIRCRAFT_DELAY': {'pct': 3.1, 'ci95': (2.7, 3.6), 'n': 5998}, 'prev_leg': {'pct': 8.1, 'ci95': (7.3, 9.0), 'n': 4002}}
- **escalated_no_safe_plan**: {'pct': 2.6, 'ci95': (2.3, 2.9), 'n': 10000}
- **airborne_holding_share**: {'pct': 1.6, 'ci95': (1.4, 1.9), 'n': 10000}
- **airborne_holding_min_when_any**: {'mean': np.float64(3.8), 'p50': np.float64(3.0), 'p90': np.float64(7.0)}
- **fuel_saved_kg_per_flight**: {'mean': 2, 'median': 0, 'mean_without_top_1pct': 0}
- **mean_delay_status_quo_vs_solver**: [np.float64(64.4), np.float64(62.2)]
- **top_destinations_unsafe**: {'ATL': {'pct': 5.7, 'ci95': (4.0, 8.1), 'n': 506}, 'BOS': {'pct': 5.9, 'ci95': (3.6, 9.7), 'n': 236}, 'DEN': {'pct': 6.5, 'ci95': (4.3, 9.5), 'n': 356}, 'DFW': {'pct': 7.3, 'ci95': (5.3, 9.9), 'n': 482}, 'EWR': {'pct': 6.8, 'ci95': (4.3, 10.8), 'n': 234}, 'IAH': {'pct': 6.8, 'ci95': (4.3, 10.5), 'n': 265}, 'LAS': {'pct': 4.3, 'ci95': (2.4, 7.5), 'n': 257}, 'LAX': {'pct': 6.2, 'ci95': (4.2, 9.3), 'n': 352}, 'MCO': {'pct': 7.6, 'ci95': (4.8, 11.9), 'n': 223}, 'ORD': {'pct': 6.4, 'ci95': (4.7, 8.7), 'n': 590}, 'PHX': {'pct': 5.1, 'ci95': (3.0, 8.6), 'n': 254}, 'SFO': {'pct': 7.1, 'ci95': (4.6, 10.7), 'n': 282}}
