import { getCollectionStats } from './main.js'
import { TableComponent } from './table.js'


function renderState(value) {
    const params = new URLSearchParams({state: value})
    return $('<a/>')
        .attr({href: `/feed?${params}`, title: value})
        .text(value)
}

const components = [
    {
        id: 'collection_stats',
        title: 'Collection Stats',
        columns: [
            {title: 'Name', name: 'name'},
            {title: 'Records', name: 'count', type: 'num'},
            {title: 'Size', name: 'size', type: 'num'},
        ],
        data: async () => (await getCollectionStats()).values(),
    },
    {
        id: 'state_stats',
        title: 'State Stats',
        collection: 'states',
        columns: [
            {title: 'State', name: 'id', render: renderState},
            {title: 'Reports', name: 'reports_count', type: 'num'},
            {title: 'Last Reported', name: 'last_reported', type: 'date'},
        ],
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


export async function renderPage(target) {
    await getCollectionStats()
    target = $(target).empty()
    for (const task of components.map(it => it.build())) {
        target.append(await task)
    }
}
