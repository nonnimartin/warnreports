import { cache } from './main.js'
import { TableComponent } from './table.js'


function renderState(value) {
    const params = new URLSearchParams({state: value})
    return $('<a/>')
        .attr({href: `/feed?${params}`, title: value})
        .text(value)
}

class AboutComponent {

    constructor() {
        this.components = [
            {
                id: 'collection_stats',
                title: 'Collection Stats',
                columns: [
                    {title: 'Name', name: 'name'},
                    {title: 'Records', name: 'count', type: 'num'},
                    {title: 'Size', name: 'size', type: 'num'},
                ],
                data: async () => Object.values((await cache.fetch('stats')).collections),
            },
            {
                id: 'state_stats',
                title: 'State Stats',
                columns: [
                    {title: 'State', name: 'id', render: renderState},
                    {title: 'Reports', name: 'reports_count', type: 'num'},
                    {title: 'Last Reported', name: 'last_reported', type: 'date'},
                ],
                data: () => cache.fetch('states')
            },
            {
                id: 'naics_stats',
                title: 'NAICS Stats',
                collection: 'naics',
                params: {reports_count_min: 1, depth_max: 0},
                columns: [
                    {title: 'ID', name: 'id'},
                    {title: 'Title', name: 'title'},
                    {title: 'Reports', name: 'reports_count', type: 'num'},
                ],
            }
        ].map(defn => new TableComponent({
            ...defn,
            opts: {
                paging: false,
                filter: false,
                layout: {
                    bottomStart: null,
                },
            },
        }))
        this.wrapper = $('<div/>').append(this.components.map(it => it.wrapper))
    }

    async build() {
        await cache.fetch('stats')
        for (const task of this.components.map(it => it.build())) {
            await task
        }
        return this.wrapper
    }
}

export default new AboutComponent
