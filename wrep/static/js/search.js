;(() => {

    const REDRAW_DELAY = 100

    function cleanDtParams(data) {
        data.limit = data.length
        data.offset = data.start
        delete data.length
        delete data.start
        delete data.columns
        delete data.search
        const orders = []
        for (let {name, dir} of data.order) {
            if (dir === 'desc') {
                name = `-${name}`
            }
            orders.push(name)
        }
        delete data.order
        if (orders.length) {
            data.order = orders.join(',')
        }
    }

    function getSearchFormParams(form) {
        const params = new URLSearchParams()
        const formData = new FormData($(form).get(0))
        for (const [field, value] of formData.entries()) {
            if (value.length) {
                params.set(field, value)
            }
        }
        return params
    }

    function strunc(str, len) {
        if (str.length > len) {
            str = str.substring(0, len - 4) + ' ...'
        }
        return str
    }
    $(() => {

        const renderDate = v => v ? v.substring(0, 10) : ''
        const renderCompany = (v, type, row) => $('<a/>')
            .attr({href: `/r/${row.id}`, title: v})
            .text(strunc(v, 50))
            .get(0)
            .outerHTML
        const renderAction = v => v ? strunc(v, 20) : ''
        const columns = [
            {name: 'state'},
            {name: 'company', render: renderCompany},
            {name: 'reported', type: 'date', render: renderDate},
            {name: 'starting', type: 'date', render: renderDate},
            {name: 'employees', type: 'num'},
            {name: 'action', orderable: false, render: renderAction},
        ]
    
        for (const col of columns) {
            col.data = col.data || col.name
            col.className = `field-${col.name}`
        }

        const table = $('#search_table')
        const form = $('#search_form')
        const clearForm = $('.clear-form', form)

        let reqTimeout

        const doDraw = () => {
            table.DataTable().draw()
        }
        const queueDraw = () => {
            clearTimeout(reqTimeout)
            reqTimeout = setTimeout(doDraw, REDRAW_DELAY)
        }
        form
            .on('submit', e => {
                e.preventDefault()
                queueDraw()
            })
            .on('change keyup keydown', queueDraw)
        
        clearForm.on('click', () => {
            $(':input', form).val('')
        })

        table.DataTable({
            processing: true,
            serverSide: true,
            pageLength: 25,
            columns,
            order: {
                name: 'reported',
                dir: 'desc',
            },
            layout: {
                topStart: form,
                topEnd: null,
                bottomStart: 'pageLength',
                bottomEnd: 'paging',
                bottom2Start: 'info'
            },
            ajax: {
                url: '/dt/reports',
                data: data => {
                    cleanDtParams(data)
                    const params = getSearchFormParams(form)
                    Object.assign(data, Object.fromEntries(params.entries()))
                    if (data.text && data.text.length < 2) {
                        delete data.text
                    }
                },
            },
            stateSave: true,
            stateSaveParams: (settings, data) => {
                const params = getSearchFormParams(form)
                Object.assign(data, Object.fromEntries(params.entries()))
            },
            stateLoadParams: (settings, data) => {
                const formData = new FormData($(form).get(0))
                for (const key of formData.keys()) {
                    if (data[key]) {
                        $(`:input[name="${key}"]`, form).val(data[key])
                    }
                }
            }
        })
    })
})();