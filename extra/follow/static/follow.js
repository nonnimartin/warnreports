$(function () {

    $('#company, #email').keyup(function () {
        const disabled = !$('#email').val() || !$('#company').val()
        $('#submitBtn').prop({ disabled })
    })

    // Add a click event handler for the submit button
    $('#submitBtn').click(function () {
        const email = $('#email').val()
        const company = $('#company').val()
        $.ajax({
            url: '/follow/new',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ company, email }),
            success: function (response) {
                // Handle the API response here
                console.log(response)
            },
            error: function (error) {
                // Handle errors here
                console.error(error)
            }
        })
    })

    const limit = 20
    $('.tt-query').typeahead({
        hint: true,
        highlight: true,
        minLength: 3,
    }, {
        name: 'search-results',
        source: new Bloodhound({
            remote: {
                url: `/api/v0/companies?company=%QUERY&limit=${limit}`,
                wildcard: '%QUERY',
            },
            datumTokenizer: Bloodhound.tokenizers.whitespace,
            queryTokenizer: Bloodhound.tokenizers.whitespace
        }),
        limit,
        display: 'company',
        templates: {
            suggestion: data => $('<p/>').text(data.company).addClass('tt-suggestion')
        }
    })
});