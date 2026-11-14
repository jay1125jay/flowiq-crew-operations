"""Continue the original dashboard's PAPER accounts in the dedicated PC state directory."""
import argparse
import asyncio
import json
from functools import partial
from pathlib import Path

import category_realtime_runtime as categories
import pc_runtime


class OriginalState(categories.CategoryState):
    def read(self):
        if self.path.is_file():
            return super().read()
        snapshot = categories.ROOT / 'trader-discovery' / 'category-paper.json'
        state = json.loads(snapshot.read_text(encoding='utf-8'))
        if not state or not state.get('observed_source_at'):
            raise ValueError('Original dashboard snapshot is incomplete')
        categories._validate_category_state(state)
        source = state['observed_source_at']
        state['original_dashboard_seed_at'] = state['updated_at']
        self.save(state, source)
        return state, source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--open-browser', action='store_true')
    parser.add_argument('--share-phone', action='store_true')
    parser.add_argument('--seconds', type=int, default=0)
    args = parser.parse_args()
    if Path(args.state_dir).name != 'original-dashboard-state':
        parser.error('Use the dedicated original-dashboard-state directory')
    categories.CategoryState = OriginalState
    categories.base.SOURCE_REFRESH_SECONDS = 10
    collector = pc_runtime.pc_source_collector
    collector.collect_sources = partial(collector.collect_sources, position_interval=categories.base.SOURCE_REFRESH_SECONDS)
    asyncio.run(pc_runtime.run(args))


if __name__ == '__main__':
    main()
