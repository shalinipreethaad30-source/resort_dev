(function () {

    /* ═══════════════════════════════════
       CLOCK — updates every 10 seconds
    ═══════════════════════════════════ */
    function tickClock() {
        const timeEl = document.getElementById('clockTime')
        const dateEl = document.getElementById('clockDate')
        if (!timeEl && !dateEl) return

        const now = new Date()
        const hh  = String(now.getHours()).padStart(2, '0')
        const mm  = String(now.getMinutes()).padStart(2, '0')
        const D   = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
        const M   = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

        if (timeEl) timeEl.textContent = hh + ':' + mm
        if (dateEl) dateEl.textContent = D[now.getDay()] + ', ' + now.getDate() + ' ' + M[now.getMonth()]
    }

    /* ═══════════════════════════════════
       ROOM DATA — updates every 5 seconds
    ═══════════════════════════════════ */
    const roomNo = new URLSearchParams(window.location.search).get('room_no')
        || window.location.pathname.split('/').pop()

    window.ROOM_NO = roomNo

    async function loadRoomData() {
        const guestEl   = document.getElementById('guestName')
        const roomEl    = document.getElementById('roomNo')
        const messageEl = document.getElementById('customMessage')

        if (!guestEl && !roomEl && !messageEl) return

        try {
            const data = await fetch(`/api/room-data/${roomNo}?t=${Date.now()}`, {
                cache: 'no-store',
                headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache' }
            }).then(r => r.json())

            console.log("API DATA:", data)

            if (guestEl)
                guestEl.innerHTML = 'Welcome, <em>' + data.name + '</em>'

            if (roomEl)
                roomEl.textContent = 'Room ' + roomNo

            // ✅ Uses live message from admin (falls back to default)
            if (messageEl)
                messageEl.textContent = data.message || "Have a nice stay"

        } catch (e) {
            console.error("Error loading room data:", e)
        }
    }

    window.onload = () => {
    loadRoomData()
    setInterval(loadRoomData, 5000)  // poll every 5 seconds
    }


    /* ═══════════════════════════════════
       ACTIVITIES — updates every 10 seconds
    ═══════════════════════════════════ */
    let actPending = null

    async function loadActivities() {
        const el = document.getElementById('activities-list')
        if (!el) return

        try {
            const data = await fetch('/api/activities').then(r => r.json())
            if (!data.length) {
                el.innerHTML = '<div class="act-card">No experiences scheduled today.</div>'
                return
            }
            el.innerHTML = data.map(a => `
                <div class="act-card">
                    ${a.is_announcement
                        ? `<span class="ann-badge">Announcement</span><strong>${a.title}</strong>`
                        : `<strong>${a.title}</strong><small>${a.time_slot || ''}</small>
                           <button class="reserve-pill"
                               onclick="openActConfirm(${a.id},'${(a.title||'').replace(/'/g,"\\'")}','${(a.time_slot||'').replace(/'/g,"\\'")}');event.stopPropagation()">
                               Reserve
                           </button>`
                    }
                </div>
            `).join('')
        } catch (e) {}
    }

    window.openActConfirm = function (id, title, timeSlot) {
        actPending = { id, title, timeSlot }
        const set = (elId, val) => { const el = document.getElementById(elId); if (el) el.textContent = val }
        set('actConfirmName', title)
        set('actConfirmSlot', timeSlot || '—')
        set('actConfirmRoom', 'Room ' + (window.ROOM_NO || '—'))
        const btn = document.getElementById('actBookBtn')
        if (btn) { btn.textContent = 'Confirm Reservation'; btn.disabled = false; btn.style.background = '' }
        const overlay = document.getElementById('actConfirmOverlay')
        if (overlay) overlay.classList.add('active')
    }

    window.closeActConfirm = function () {
        const overlay = document.getElementById('actConfirmOverlay')
        if (overlay) overlay.classList.remove('active')
        actPending = null
    }

    window.confirmActBooking = async function () {
        if (!actPending) return
        const btn = document.getElementById('actBookBtn')
        if (btn) { btn.disabled = true; btn.textContent = 'Reserving\u2026' }
        try {
            await fetch('/api/activity-booking', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    room_no:   window.ROOM_NO,
                    activity_id: actPending.id,
                    title:     actPending.title,
                    time_slot: actPending.timeSlot,
                })
            }).catch(() => {})
        } catch (e) {}
        window.closeActConfirm()
        const toast = document.getElementById('actToast')
        if (toast) { toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 3000) }
        _showOrderAlert('Activity reserved! Will auto-confirm in 10 mins.')
        loadMyOrders()
    }

    /* ═══════════════════════════════════
       SERVICES — updates every 30 seconds
    ═══════════════════════════════════ */
    const SVC_REGISTRY = {
        food: {
            keywords:  ['food', 'menu'],
            opener:    'openFoodMenu',
            sub:       'Order directly to your room',
            overlayId: 'foodOverlay',
        },
        roomservice: {
            keywords:  ['room service', 'housekeeping', 'cleaning', 'laundry', 'towel'],
            opener:    'openRoomServiceMenu',
            sub:       'Housekeeping & in-room requests',
            overlayId: 'roomServiceOverlay',
        },
        spa: {
            keywords:  ['spa', 'wellness', 'massage', 'facial', 'body treatment'],
            opener:    'openSpaMenu',
            sub:       'Relax & refresh',
            overlayId: 'spaOverlay',
        },
        bar: {
            keywords:  ['bar', 'cocktail', 'mocktail', 'drinks', 'beverage'],
            opener:    'openBarMenu',
            sub:       'Cocktails & mocktails',
            overlayId: 'barOverlay',
        },
        dine: {
            keywords:  ['dine', 'dining', 'restaurant', 'fine dining'],
            opener:    'openDineMenu',
            sub:       'Fine dining experience',
            overlayId: 'dineOverlay',
        },
        entertainment: {
            keywords:  ['entertainment', 'activities', 'activity', 'indoor', 'outdoor', 'games', 'sports'],
            opener:    'openEntMenu',
            sub:       'Fun for everyone',
            overlayId: 'entOverlay',
        },
        pool: {
            keywords:  ['pool', 'swim', 'jacuzzi'],
            opener:    'openPoolMenu',
            sub:       'Heated rooftop pool',
            overlayId: 'poolOverlay',
        },
        myorders: {
            keywords:  ['my orders', 'my bookings', 'bill', 'charges'],
            opener:    'openMyOrders',
            sub:       'Your bookings & charges',
            overlayId: 'myOrdersOverlay',
        },
        gallery: {
            keywords:  ['gallery', 'photo', 'infrastructure', 'amenities', 'amenity', 'resort tour'],
            opener:    'openGalleryMenu',
            sub:       'Explore our resort',
            overlayId: 'galleryOverlay',
        },
    }

    function _resolveRegistryEntry(s) {
        if (s.overlay_key && SVC_REGISTRY[s.overlay_key]) {
            return SVC_REGISTRY[s.overlay_key]
        }
        const t = (s.title || '').toLowerCase()
        for (const entry of Object.values(SVC_REGISTRY)) {
            if (entry.keywords.some(kw => t.includes(kw))) return entry
        }
        return null
    }

    function getSub(s) {
        const entry = _resolveRegistryEntry(s)
        return entry ? entry.sub : (s.subtitle || 'Tap to explore')
    }

    function _buildOnclick(s) {
        const entry = _resolveRegistryEntry(s)
        if (!entry) return `window.location.href='${s.url || '#'}'`
        return `if(typeof window['${entry.opener}']==='function') window['${entry.opener}'](); else console.warn('${entry.opener} not found — is the overlay present in this template?')`
    }

    function buildServiceCard(s) {
        return `
            <div class="svc-card" onclick="${_buildOnclick(s)}" style="cursor:pointer;">
                <div class="svc-img" style="background-image:url('${s.image_url || ''}');"></div>
                <div class="svc-arrow">›</div>
                <div class="svc-info">
                    <div class="svc-title">${s.title}</div>
                    <div class="svc-sub">${getSub(s)}</div>
                </div>
            </div>`
    }

    async function loadServices() {
        const el = document.getElementById('services-container')
        if (!el) return

        try {
            const services = await fetch('/api/services').then(r => r.json())
            if (!Array.isArray(services) || !services.length) {
                el.innerHTML = `<div class="svc-card"><div class="svc-info"><div class="svc-title">No services available</div></div></div>`
                return
            }
            el.innerHTML = services.map(buildServiceCard).join('')
        } catch (e) {
            const el = document.getElementById('services-container')
            if (el) el.innerHTML = `<div class="svc-card"><div class="svc-info"><div class="svc-title">Unable to load services</div></div></div>`
        }
    }


    /* ═══════════════════════════════════════════════════════════════
       FOOD MENU
    ═══════════════════════════════════════════════════════════════ */
    const FOOD_CATEGORIES = [
        { id: 'breakfast', name: 'Breakfast', sub: 'Start your day fresh'   },
        { id: 'lunch',     name: 'Lunch',     sub: 'Hearty midday meals'    },
        { id: 'dinner',    name: 'Dinner',    sub: 'Delicious night dining' },
        { id: 'snacks',    name: 'Snacks',    sub: 'Quick bites'            },
        { id: 'desserts',  name: 'Desserts',  sub: 'Sweet treats'           },
        { id: 'drinks',    name: 'Drinks',    sub: 'Refresh yourself'       },
    ]

    let foodCart     = {}
    let foodScreen   = 'categories'
    let foodCatItems = []

    window.openFoodMenu = async function () {
        const overlay = document.getElementById('foodOverlay')
        if (!overlay) return
        overlay.classList.add('active')
        document.body.style.overflow = 'hidden'
        _showFoodCategoryScreen()
        await _loadFoodCategoryPreviews()
    }

    function _closeFoodMenu() {
        const overlay = document.getElementById('foodOverlay')
        if (overlay) overlay.classList.remove('active')
        document.body.style.overflow = ''
    }

    window.foodGoBack = function () {
        if (foodScreen === 'items') _showFoodCategoryScreen()
        else _closeFoodMenu()
    }

    function _showFoodCategoryScreen() {
        foodScreen = 'categories'
        const catScreen  = document.getElementById('foodCategoryScreen')
        const itemScreen = document.getElementById('foodItemsScreen')
        const title      = document.getElementById('foodPageTitle')
        const backLabel  = document.getElementById('foodBackLabel')
        if (catScreen)  catScreen.style.display = 'flex'
        if (itemScreen) itemScreen.classList.remove('visible')
        if (title)      title.innerHTML = 'Food <em>Menu</em>'
        if (backLabel)  backLabel.textContent = 'Home'
    }

    window.showFoodItemsScreen = async function (catId, catName) {
        foodScreen = 'items'
        const catScreen  = document.getElementById('foodCategoryScreen')
        const itemScreen = document.getElementById('foodItemsScreen')
        const title      = document.getElementById('foodPageTitle')
        const backLabel  = document.getElementById('foodBackLabel')
        const catLabel   = document.getElementById('itemsCatLabel')
        const scroll     = document.getElementById('itemsScroll')
        if (catScreen)  catScreen.style.display = 'none'
        if (itemScreen) itemScreen.classList.add('visible')
        if (title)      title.innerHTML = catName + ' <em>Menu</em>'
        if (backLabel)  backLabel.textContent = 'Categories'
        if (catLabel)   catLabel.textContent = catName.toUpperCase() + ' MENU'
        if (scroll)     scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;">Loading\u2026</div>'
        await _loadFoodItems(catId)
    }

    async function _loadFoodCategoryPreviews() {
        const grid = document.getElementById('catGrid')
        if (!grid) return

        grid.innerHTML = FOOD_CATEGORIES.map(c => `
            <div class="cat-card cat-loading" id="cat-${c.id}"
                 onclick="showFoodItemsScreen('${c.id}','${c.name}')">
                <div class="cat-card-img" id="catimg-${c.id}" style="background:#1a0510;"></div>
                <div class="cat-card-body">
                    <div class="cat-card-name">${c.name}</div>
                    <div class="cat-card-sub">${c.sub}</div>
                </div>
            </div>`).join('')

        let covers = {}
        try { covers = await fetch('/api/category-covers/food').then(r => r.json()) } catch (e) {}

        await Promise.allSettled(FOOD_CATEGORIES.map(async c => {
            const imgEl = document.getElementById('catimg-' + c.id)
            if (!imgEl) return
            if (covers[c.id]) {
                imgEl.style.backgroundImage = `url('${covers[c.id]}')`
                imgEl.style.backgroundSize = 'cover'
                imgEl.style.backgroundPosition = 'center'
                return
            }
            try {
                const items = await fetch(`/api/food-items?category=${c.id}`).then(r => r.json())
                if (items.length && items[0].image_url) {
                    imgEl.style.backgroundImage = `url('${items[0].image_url}')`
                    imgEl.style.backgroundSize = 'cover'
                    imgEl.style.backgroundPosition = 'center'
                }
                if (!items.length) {
                    const card = document.getElementById('cat-' + c.id)
                    if (card) { card.style.opacity = '0.4'; card.style.cursor = 'default'; card.onclick = null }
                }
            } catch (e) {}
        }))
    }

    async function _loadFoodItems(catId) {
        const scroll = document.getElementById('itemsScroll')
        try {
            const items = await fetch(`/api/food-items?category=${catId}`).then(r => r.json())
            foodCatItems = items.map(i => ({ id: i.id, name: i.title, price: i.price, image_url: i.image_url }))
            _renderFoodItems()
        } catch (e) {
            if (scroll) scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;">Failed to load items.</div>'
        }
    }

    function _renderFoodItems() {
        const el = document.getElementById('itemsScroll')
        if (!el) return
        if (!foodCatItems.length) {
            el.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;">No items in this category yet.</div>'
            return
        }
        el.innerHTML = foodCatItems.map(item => {
            const qty = foodCart[item.id] ? foodCart[item.id].qty : 0
            return `
                <div class="item-card" id="icard-${item.id}">
                    <div class="item-img" style="background-image:url('${item.image_url}');background-size:cover;background-position:center;"></div>
                    <div class="item-body">
                        <div class="item-name">${item.name}</div>
                        <div class="item-price"><small>\u20b9</small>${item.price}</div>
                        <div class="qty-row">
                            <button class="qty-btn minus" onclick="changeFoodQty(${item.id},-1)">\u2212</button>
                            <span class="qty-val" id="qty-${item.id}">${qty}</span>
                            <button class="qty-btn plus"  onclick="changeFoodQty(${item.id},+1)">+</button>
                        </div>
                    </div>
                </div>`
        }).join('')
    }

    window.changeFoodQty = function (id, delta) {
        const item = foodCatItems.find(i => i.id === id)
        if (!item) return
        if (!foodCart[id]) foodCart[id] = { ...item, qty: 0 }
        foodCart[id].qty = Math.max(0, foodCart[id].qty + delta)
        if (foodCart[id].qty === 0) delete foodCart[id]
        const qtyEl = document.getElementById('qty-' + id)
        if (qtyEl) qtyEl.textContent = foodCart[id] ? foodCart[id].qty : 0
        _updateFoodCartPanel()
    }

    function _updateFoodCartPanel() {
        const items   = Object.values(foodCart)
        const total   = items.reduce((s, i) => s + i.price * i.qty, 0)
        const totalEl = document.getElementById('cartTotal')
        if (totalEl) totalEl.textContent = total
        const listEl = document.getElementById('cartList')
        if (listEl) {
            listEl.innerHTML = items.length
                ? items.map(i => `
                    <div class="cart-item-row">
                        <div>
                            <div class="ci-name">${i.name}</div>
                            <div class="ci-qty">\u00d7${i.qty}</div>
                        </div>
                        <div class="ci-price">\u20b9${i.price * i.qty}</div>
                    </div>`).join('')
                : '<div class="cart-empty">No items yet</div>'
        }
        const placeBtn = document.getElementById('placeOrderBtn')
        if (placeBtn) placeBtn.disabled = items.length === 0
    }

    window.clearCart = function () {
        foodCart = {}
        document.querySelectorAll('.qty-val').forEach(el => el.textContent = '0')
        _updateFoodCartPanel()
    }

    window.placeOrder = async function () {
        const items = Object.values(foodCart)
        if (!items.length) return
        const btn = document.getElementById('placeOrderBtn')
        if (btn) { btn.disabled = true; btn.textContent = 'Placing\u2026' }
        try {
            await fetch('/api/order', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    room_no: window.ROOM_NO,
                    items:   items.map(i => ({ id: i.id, name: i.name, qty: i.qty, price: i.price })),
                    total:   items.reduce((s, i) => s + i.price * i.qty, 0),
                })
            }).catch(() => {})
        } catch (e) {}
        if (btn) { btn.textContent = '\u2713 Order Placed!'; btn.style.background = '#1abc9c' }

        const foodToast = document.getElementById('foodToast')
        if (foodToast) { foodToast.classList.add('show') }

        setTimeout(() => {
            window.clearCart()
            if (btn) { btn.textContent = 'Place Order'; btn.style.background = '' }
            if (foodToast) foodToast.classList.remove('show')
        }, 2500)
    }


    /* ═══════════════════════════════════════════════════════════════
       SPA & WELLNESS
    ═══════════════════════════════════════════════════════════════ */
    const SPA_CATEGORIES = [
        { id: 'massage', name: 'Massage', sub: 'Deep tissue & relaxation', icon: '\ud83d\udc86' },
        { id: 'facial',  name: 'Facial',  sub: 'Glow & rejuvenation',      icon: '\u2728'       },
        { id: 'body',    name: 'Body',    sub: 'Wraps, scrubs & soaks',    icon: '\ud83c\udf38' },
        { id: 'other',   name: 'Other',   sub: 'Specialty treatments',     icon: '\ud83c\udf3f' },
    ]

    let spaScreen  = 'categories'
    let spaItems   = []
    let spaPending = null
    const spaSlots = {}

    window.openSpaMenu = async function () {
        const overlay = document.getElementById('spaOverlay')
        if (!overlay) return
        overlay.classList.add('active')
        document.body.style.overflow = 'hidden'
        _showSpaCategoryScreen()
        await _loadSpaCategoryPreviews()
    }

    function _closeSpaMenu() {
        const overlay = document.getElementById('spaOverlay')
        if (overlay) overlay.classList.remove('active')
        document.body.style.overflow = ''
    }

    window.spaGoBack = function () {
        if (spaScreen === 'treatments') _showSpaCategoryScreen()
        else _closeSpaMenu()
    }

    function _showSpaCategoryScreen() {
        spaScreen = 'categories'
        const catScreen = document.getElementById('spaCategoryScreen')
        const trtScreen = document.getElementById('spaTreatmentsScreen')
        const title     = document.getElementById('spaPageTitle')
        const backLabel = document.getElementById('spaBackLabel')
        if (catScreen) catScreen.style.display = 'flex'
        if (trtScreen) trtScreen.classList.remove('visible')
        if (title)     title.innerHTML = 'Spa &amp; <em>Wellness</em>'
        if (backLabel) backLabel.textContent = 'Home'
    }

    window.showSpaTreatmentsScreen = async function (catId, catName) {
        spaScreen = 'treatments'
        const catScreen = document.getElementById('spaCategoryScreen')
        const trtScreen = document.getElementById('spaTreatmentsScreen')
        const title     = document.getElementById('spaPageTitle')
        const backLabel = document.getElementById('spaBackLabel')
        const trtLabel  = document.getElementById('spaTreatmentsLabel')
        const scroll    = document.getElementById('spaTreatmentsScroll')
        if (catScreen) catScreen.style.display = 'none'
        if (trtScreen) trtScreen.classList.add('visible')
        if (title)     title.innerHTML = catName + ' <em>Treatments</em>'
        if (backLabel) backLabel.textContent = 'Categories'
        if (trtLabel)  trtLabel.textContent = catName.toUpperCase() + ' TREATMENTS'
        if (scroll)    scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">Loading\u2026</div>'
        await _loadSpaItems(catId)
    }

    async function _loadSpaCategoryPreviews() {
        const grid = document.getElementById('spaCatGrid')
        if (!grid) return

        grid.innerHTML = SPA_CATEGORIES.map(c => `
            <div class="spa-cat-card" id="spa-cat-${c.id}"
                 onclick="showSpaTreatmentsScreen('${c.id}','${c.name}')">
                <div class="spa-cat-img" id="spa-catimg-${c.id}"></div>
                <div class="spa-cat-body">
                    <div class="spa-cat-name">${c.icon} ${c.name}</div>
                    <div class="spa-cat-sub">${c.sub}</div>
                </div>
            </div>`).join('')

        let covers = {}
        try { covers = await fetch('/api/category-covers/spa').then(r => r.json()) } catch (e) {}

        await Promise.allSettled(SPA_CATEGORIES.map(async c => {
            const imgEl = document.getElementById('spa-catimg-' + c.id)
            if (!imgEl) return
            if (covers[c.id]) {
                imgEl.style.backgroundImage = `url('${covers[c.id]}')`
                imgEl.style.backgroundSize = 'cover'
                imgEl.style.backgroundPosition = 'center'
                return
            }
            try {
                const items = await fetch(`/api/spa-items?category=${c.id}`).then(r => r.json())
                if (items.length && items[0].image_url) {
                    imgEl.style.backgroundImage = `url('${items[0].image_url}')`
                    imgEl.style.backgroundSize = 'cover'
                    imgEl.style.backgroundPosition = 'center'
                }
                if (!items.length) {
                    const card = document.getElementById('spa-cat-' + c.id)
                    if (card) { card.style.opacity = '.4'; card.style.cursor = 'default'; card.onclick = null }
                }
            } catch (e) {}
        }))
    }

    async function _loadSpaItems(catId) {
        const scroll = document.getElementById('spaTreatmentsScroll')
        try {
            spaItems = await fetch(`/api/spa-items?category=${catId}`).then(r => r.json())
            _renderSpaItems()
        } catch (e) {
            if (scroll) scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">Failed to load.</div>'
        }
    }

    function _renderSpaItems() {
        const el = document.getElementById('spaTreatmentsScroll')
        if (!el) return
        if (!spaItems.length) {
            el.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">No treatments in this category yet.</div>'
            return
        }
        el.innerHTML = spaItems.map(item => _spaTreatmentCard(item)).join('')
    }

    let spaExpandedId = null

    function _spaTreatmentCard(item) {
        const cat = item.category.charAt(0).toUpperCase() + item.category.slice(1)
        return `
            <div class="spa-treatment-card" id="spa-card-${item.id}"
                 onclick="toggleSpaCard(${item.id})">
                <div class="spa-treatment-bg" style="background-image:url('${item.image_url}');background-size:cover;background-position:center;">
                    <div class="spa-card-overlay-label">
                        <div class="spa-treatment-name">${item.title}</div>
                        <span class="spa-treatment-price">${item.price ? '₹' + item.price : ''}</span>
                        <div class="spa-treatment-desc">${cat}</div>
                        <div class="spa-card-tap-hint">Tap to book</div>
                    </div>
                </div>
                <div class="spa-slot-panel" id="spa-panel-${item.id}">
                    ${_buildSpaSlotPanel(item)}
                </div>
            </div>`
    }

    function _buildSpaSlotPanel(item) {
        const slots  = [item.slot1, item.slot2, item.slot3].filter(Boolean)
        const selIdx = spaSlots[item.id] !== undefined ? spaSlots[item.id] : -1
        const badges = slots.length
            ? slots.map((s, i) => `
                <button class="spa-slot-badge${i === selIdx ? ' selected' : ''}"
                        onclick="selectSpaSlot(${item.id},${i},event)">${s}</button>`).join('')
            : '<span style="color:rgba(255,255,255,.3);font-size:11px;font-style:italic;">No slots available</span>'
        const btnLabel = selIdx >= 0 ? `Book ${slots[selIdx]}` : 'Book Slot'
        return `
            <div class="spa-slots">${badges}</div>
            ${slots.length
                ? `<button class="spa-book-slot-btn" id="spa-bookbtn-${item.id}"
                           onclick="openSpaConfirm(${item.id});event.stopPropagation()">${btnLabel}</button>`
                : ''}`
    }

    window.toggleSpaCard = function (itemId) {
        const card = document.getElementById('spa-card-' + itemId)
        if (!card) return
        const isOpen = card.classList.contains('expanded')
        if (spaExpandedId !== null && spaExpandedId !== itemId) {
            const prevCard = document.getElementById('spa-card-' + spaExpandedId)
            if (prevCard) prevCard.classList.remove('expanded')
        }
        if (isOpen) { card.classList.remove('expanded'); spaExpandedId = null }
        else         { card.classList.add('expanded');   spaExpandedId = itemId }
    }

    window.selectSpaSlot = function (itemId, slotIdx, e) {
        e.stopPropagation()
        spaSlots[itemId] = slotIdx
        const card  = document.getElementById('spa-card-' + itemId)
        if (!card) return
        card.querySelectorAll('.spa-slot-badge').forEach((b, i) =>
            b.classList.toggle('selected', i === slotIdx))
        const item  = spaItems.find(i => i.id === itemId)
        const slots = [item.slot1, item.slot2, item.slot3].filter(Boolean)
        const btn   = document.getElementById('spa-bookbtn-' + itemId)
        if (btn) btn.textContent = `Book ${slots[slotIdx]}`
    }

    window.openSpaConfirm = function (itemId) {
        const item = spaItems.find(i => i.id === itemId)
        if (!item) return
        const slots    = [item.slot1, item.slot2, item.slot3].filter(Boolean)
        const selIdx   = spaSlots[itemId] !== undefined ? spaSlots[itemId] : 0
        const slotTime = slots[selIdx] || slots[0] || '\u2014'
        spaSlots[itemId] = selIdx
        spaPending = { item, slotTime }

        const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val }
        set('spaConfirmName', item.title)
        set('spaConfirmCat',  item.category.charAt(0).toUpperCase() + item.category.slice(1))
        set('spaConfirmSlot', slotTime)
        set('spaConfirmRoom', 'Room ' + (window.ROOM_NO || '\u2014'))
        set('spaConfirmPrice', item.price && item.price > 0 ? '\u20b9' + item.price : 'Complimentary')
        set('spaConfirmSub',  'Your treatment slot will be reserved')

        const priceRow = document.getElementById('spaConfirmPriceRow')
        const priceEl  = document.getElementById('spaConfirmPrice')
        if (priceRow && priceEl) {
            if (item.price && item.price > 0) {
                priceEl.textContent    = '\u20b9' + item.price
                priceRow.style.display = 'flex'
            } else {
                priceRow.style.display = 'none'
            }
        }

        const btn = document.getElementById('spaBookBtn')
        if (btn) { btn.textContent = 'Confirm Booking'; btn.disabled = false; btn.style.background = '' }
        const overlay = document.getElementById('spaConfirmOverlay')
        if (overlay) overlay.classList.add('active')
    }

    window.closeSpaConfirm = function () {
        const overlay = document.getElementById('spaConfirmOverlay')
        if (overlay) overlay.classList.remove('active')
        spaPending = null
    }

    window.confirmSpaBooking = async function () {
        if (!spaPending) return
        const btn = document.getElementById('spaBookBtn')
        if (btn) { btn.disabled = true; btn.textContent = 'Booking\u2026' }
        try {
            await fetch('/api/spa-booking', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    room_no:    window.ROOM_NO,
                    item_id:    spaPending.item.id,
                    item_title: spaPending.item.title,
                    category:   spaPending.item.category,
                    slot:       spaPending.slotTime,
                    price:      spaPending.item.price || 0,
                })
            }).catch(() => {})
        } catch (e) {}
        window.closeSpaConfirm()
        const toast = document.getElementById('spaToast')
        if (toast) { toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 3000) }
        _showOrderAlert('✅ Spa booked! Will auto-confirm in 10 mins.')
        loadMyOrders()
    }


    /* ═══════════════════════════════════════════════════════════════
       BAR MENU
    ═══════════════════════════════════════════════════════════════ */
    const BAR_CATEGORIES = [
        { id: 'alcoholic',     name: 'Alcoholic Drinks',     sub: 'Beer \u2022 Wine \u2022 Spirits \u2022 Cocktails', defaultBg: 'linear-gradient(135deg,#3a1a00,#1a0800)' },
        { id: 'non-alcoholic', name: 'Non-Alcoholic Drinks', sub: 'Mocktails \u2022 Juices \u2022 Soft Drinks',       defaultBg: 'linear-gradient(135deg,#002a1a,#001208)'  },
    ]

    let barCart     = {}
    let barScreen   = 'categories'
    let barCatItems = []

    window.openBarMenu = async function () {
        const overlay = document.getElementById('barOverlay')
        if (!overlay) return
        overlay.classList.add('active')
        document.body.style.overflow = 'hidden'
        _showBarCategoryScreen()
        await _loadBarCategoryPreviews()
    }

    function _closeBarMenu() {
        const overlay = document.getElementById('barOverlay')
        if (overlay) overlay.classList.remove('active')
        document.body.style.overflow = ''
    }

    window.barGoBack = function () {
        if (barScreen === 'items') _showBarCategoryScreen()
        else _closeBarMenu()
    }

    function _showBarCategoryScreen() {
        barScreen = 'categories'
        const catScreen  = document.getElementById('barCategoryScreen')
        const itemScreen = document.getElementById('barItemsScreen')
        const title      = document.getElementById('barPageTitle')
        const backLabel  = document.getElementById('barBackLabel')
        if (catScreen)  catScreen.style.display = 'flex'
        if (itemScreen) itemScreen.classList.remove('visible')
        if (title)      title.innerHTML = 'Bar <em>Menu</em>'
        if (backLabel)  backLabel.textContent = 'Home'
    }

    window.showBarItemsScreen = async function (catId, catName) {
        barScreen = 'items'
        const catScreen  = document.getElementById('barCategoryScreen')
        const itemScreen = document.getElementById('barItemsScreen')
        const title      = document.getElementById('barPageTitle')
        const backLabel  = document.getElementById('barBackLabel')
        const catLabel   = document.getElementById('barItemsCatLabel')
        const scroll     = document.getElementById('barItemsScroll')
        if (catScreen)  catScreen.style.display = 'none'
        if (itemScreen) itemScreen.classList.add('visible')
        if (title)      title.innerHTML = catName + ' <em>Drinks</em>'
        if (backLabel)  backLabel.textContent = 'Categories'
        if (catLabel)   catLabel.textContent = catName.toUpperCase()
        if (scroll)     scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">Loading\u2026</div>'
        await _loadBarItems(catId)
    }

    async function _loadBarCategoryPreviews() {
        const grid = document.getElementById('barCatGrid')
        if (!grid) return

        grid.innerHTML = BAR_CATEGORIES.map(c => `
            <div class="bar-cat-card" id="bar-cat-${c.id}"
                 onclick="showBarItemsScreen('${c.id}','${c.name}')">
                <div class="bar-cat-img" id="bar-catimg-${c.id}"
                     style="background:${c.defaultBg};"></div>
                <div class="bar-cat-body">
                    <div class="bar-cat-name">${c.name}</div>
                    <div class="bar-cat-sub">${c.sub}</div>
                </div>
            </div>`).join('')

        let covers = {}
        try { covers = await fetch('/api/category-covers/bar').then(r => r.json()) } catch (e) {}

        await Promise.allSettled(BAR_CATEGORIES.map(async c => {
            const imgEl = document.getElementById('bar-catimg-' + c.id)
            if (!imgEl) return
            if (covers[c.id]) {
                imgEl.style.backgroundImage = `url('${covers[c.id]}')`
                imgEl.style.backgroundSize = 'cover'
                imgEl.style.backgroundPosition = 'center'
                return
            }
            try {
                const items = await fetch(`/api/bar-items?category=${c.id}`).then(r => r.json())
                if (items.length && items[0].image_url) {
                    imgEl.style.backgroundImage = `url('${items[0].image_url}')`
                    imgEl.style.backgroundSize = 'cover'
                    imgEl.style.backgroundPosition = 'center'
                }
                if (!items.length) {
                    const card = document.getElementById('bar-cat-' + c.id)
                    if (card) { card.style.opacity = '.4'; card.style.cursor = 'default'; card.onclick = null }
                }
            } catch (e) {}
        }))
    }

    async function _loadBarItems(catId) {
        const scroll = document.getElementById('barItemsScroll')
        try {
            const items = await fetch(`/api/bar-items?category=${catId}`).then(r => r.json())
            barCatItems = items.map(i => ({ id: i.id, name: i.title, price: i.price, image_url: i.image_url }))
            _renderBarItems()
        } catch (e) {
            if (scroll) scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">Failed to load drinks.</div>'
        }
    }

    function _renderBarItems() {
        const el = document.getElementById('barItemsScroll')
        if (!el) return
        if (!barCatItems.length) {
            el.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">No drinks in this category yet.</div>'
            return
        }
        el.innerHTML = barCatItems.map(item => {
            const qty = barCart[item.id] ? barCart[item.id].qty : 0
            return `
                <div class="bar-item-card" id="bcard-${item.id}">
                    <div class="bar-item-img" style="background-image:url('${item.image_url}');background-size:cover;background-position:center;"></div>
                    <div class="bar-item-body">
                        <div class="bar-item-name">${item.name}</div>
                        <div class="bar-item-price"><small>\u20b9</small>${item.price}</div>
                        <div class="bar-qty-row">
                            <button class="bar-qty-btn minus" onclick="changeBarQty(${item.id},-1)">\u2212</button>
                            <span class="bar-qty-val" id="bqty-${item.id}">${qty}</span>
                            <button class="bar-qty-btn plus"  onclick="changeBarQty(${item.id},+1)">+</button>
                        </div>
                    </div>
                </div>`
        }).join('')
    }

    window.changeBarQty = function (id, delta) {
        const item = barCatItems.find(i => i.id === id)
        if (!item) return
        if (!barCart[id]) barCart[id] = { ...item, qty: 0 }
        barCart[id].qty = Math.max(0, barCart[id].qty + delta)
        if (barCart[id].qty === 0) delete barCart[id]
        const qtyEl = document.getElementById('bqty-' + id)
        if (qtyEl) qtyEl.textContent = barCart[id] ? barCart[id].qty : 0
        _updateBarCartPanel()
    }

    function _updateBarCartPanel() {
        const items   = Object.values(barCart)
        const total   = items.reduce((s, i) => s + i.price * i.qty, 0)
        const totalEl = document.getElementById('barCartTotal')
        if (totalEl) totalEl.textContent = total
        const listEl = document.getElementById('barCartList')
        if (listEl) {
            listEl.innerHTML = items.length
                ? items.map(i => `
                    <div class="bar-cart-item-row">
                        <div>
                            <div class="bar-ci-name">${i.name}</div>
                            <div class="bar-ci-qty">\u00d7${i.qty}</div>
                        </div>
                        <div class="bar-ci-price">\u20b9${i.price * i.qty}</div>
                    </div>`).join('')
                : '<div class="bar-cart-empty">No drinks yet</div>'
        }
        const orderBtn = document.getElementById('barOrderBtn')
        if (orderBtn) orderBtn.disabled = items.length === 0
    }

    window.clearBarCart = function () {
        barCart = {}
        document.querySelectorAll('.bar-qty-val').forEach(el => el.textContent = '0')
        _updateBarCartPanel()
    }

    window.placeBarOrder = async function () {
        const items = Object.values(barCart)
        if (!items.length) return
        const btn = document.getElementById('barOrderBtn')
        if (btn) { btn.disabled = true; btn.textContent = 'Placing\u2026' }
        try {
            await fetch('/api/order', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    room_no: window.ROOM_NO,
                    order_type: 'bar',
                    items:   items.map(i => ({ id: i.id, name: i.name, qty: i.qty, price: i.price })),
                    total:   items.reduce((s, i) => s + i.price * i.qty, 0),
                })
            }).catch(() => {})
        } catch (e) {}
        if (btn) { btn.textContent = '\u2713 Order Placed!'; btn.style.background = '#1abc9c' }

        const toast = document.getElementById('barToast')
        if (toast) { toast.classList.add('show') }

        setTimeout(() => {
            window.clearBarCart()
            if (btn) { btn.textContent = 'Place Order'; btn.style.background = '' }
            if (toast) toast.classList.remove('show')
        }, 2500)
    }


    /* ═══════════════════════════════════════════════════════════════
       DINE-IN RESERVATIONS
    ═══════════════════════════════════════════════════════════════ */
    const DINE_OCCASIONS = [
        { id: 'romantic',    name: 'Romantic',    icon: '💑', sub: 'Intimate candle-light settings'   },
        { id: 'birthday',    name: 'Birthday',    icon: '🎂', sub: 'Celebrate your special day'       },
        { id: 'anniversary', name: 'Anniversary', icon: '🥂', sub: 'Mark your milestone in style'     },
        { id: 'business',    name: 'Business',    icon: '💼', sub: 'Private dining & boardroom meals'  },
        { id: 'family',      name: 'Family',      icon: '👨‍👩‍👧', sub: 'Spacious tables for everyone'  },
    ]

    let dineScreen  = 'categories'
    let dineItems   = []
    let dinePending = null
    const dineSlots = {}

    window.openDineMenu = async function () {
        const overlay = document.getElementById('dineOverlay')
        if (!overlay) return
        overlay.classList.add('active')
        document.body.style.overflow = 'hidden'
        _showDineCategoryScreen()
        await _loadDineCategoryPreviews()
    }

    function _closeDineMenu() {
        const overlay = document.getElementById('dineOverlay')
        if (overlay) overlay.classList.remove('active')
        document.body.style.overflow = ''
    }

    window.dineGoBack = function () {
        if (dineScreen === 'packages') _showDineCategoryScreen()
        else _closeDineMenu()
    }

    function _showDineCategoryScreen() {
        dineScreen = 'categories'
        const catScreen = document.getElementById('dineCategoryScreen')
        const pkgScreen = document.getElementById('dinePackagesScreen')
        const title     = document.getElementById('dinePageTitle')
        const backLabel = document.getElementById('dineBackLabel')
        if (catScreen) catScreen.style.display = 'flex'
        if (pkgScreen) pkgScreen.classList.remove('visible')
        if (title)     title.innerHTML = 'Dine-In <em>Reservations</em>'
        if (backLabel) backLabel.textContent = 'Home'
    }

    window.showDinePackagesScreen = async function (occId, occName) {
        dineScreen = 'packages'
        const catScreen = document.getElementById('dineCategoryScreen')
        const pkgScreen = document.getElementById('dinePackagesScreen')
        const title     = document.getElementById('dinePageTitle')
        const backLabel = document.getElementById('dineBackLabel')
        const pkgLabel  = document.getElementById('dinePkgLabel')
        const scroll    = document.getElementById('dinePkgScroll')
        if (catScreen) catScreen.style.display = 'none'
        if (pkgScreen) pkgScreen.classList.add('visible')
        if (title)     title.innerHTML = occName + ' <em>Packages</em>'
        if (backLabel) backLabel.textContent = 'Occasions'
        if (pkgLabel)  pkgLabel.textContent = occName.toUpperCase() + ' PACKAGES'
        if (scroll)    scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">Loading\u2026</div>'
        await _loadDineItems(occId)
    }

    async function _loadDineCategoryPreviews() {
        const grid = document.getElementById('dineCatGrid')
        if (!grid) return

        grid.innerHTML = DINE_OCCASIONS.map(o => `
            <div class="dine-cat-card" id="dine-cat-${o.id}"
                 onclick="showDinePackagesScreen('${o.id}','${o.name}')">
                <div class="dine-cat-img" id="dine-catimg-${o.id}"></div>
                <div class="dine-cat-body">
                    <div class="dine-cat-icon">${o.icon}</div>
                    <div class="dine-cat-name">${o.name}</div>
                    <div class="dine-cat-sub">${o.sub}</div>
                </div>
            </div>`).join('')

        let covers = {}
        try { covers = await fetch('/api/category-covers/dine').then(r => r.json()) } catch (e) {}

        await Promise.allSettled(DINE_OCCASIONS.map(async o => {
            const imgEl = document.getElementById('dine-catimg-' + o.id)
            if (!imgEl) return
            if (covers[o.id]) {
                imgEl.style.backgroundImage = `url('${covers[o.id]}')`
                imgEl.style.backgroundSize = 'cover'
                imgEl.style.backgroundPosition = 'center'
                return
            }
            try {
                const items = await fetch(`/api/dine-items?occasion=${o.id}`).then(r => r.json())
                if (items.length && items[0].image_url) {
                    imgEl.style.backgroundImage = `url('${items[0].image_url}')`
                    imgEl.style.backgroundSize = 'cover'
                    imgEl.style.backgroundPosition = 'center'
                }
                if (!items.length) {
                    const card = document.getElementById('dine-cat-' + o.id)
                    if (card) { card.style.opacity = '.4'; card.style.cursor = 'default'; card.onclick = null }
                }
            } catch (e) {}
        }))
    }

    async function _loadDineItems(occId) {
        const scroll = document.getElementById('dinePkgScroll')
        try {
            dineItems = await fetch(`/api/dine-items?occasion=${occId}`).then(r => r.json())
            _renderDineItems()
        } catch (e) {
            if (scroll) scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">Failed to load packages.</div>'
        }
    }

    let dineExpandedId = null

    function _renderDineItems() {
        const el = document.getElementById('dinePkgScroll')
        if (!el) return
        if (!dineItems.length) {
            el.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">No packages in this occasion yet.</div>'
            return
        }
        dineExpandedId = null
        el.innerHTML = dineItems.map(item => _dinePkgCard(item)).join('')
    }

    function _dinePkgCard(item) {
        return `
            <div class="dine-pkg-card" id="dine-card-${item.id}"
                 onclick="toggleDineCard(${item.id})">
                <div class="dine-pkg-bg" style="background-image:url('${item.image_url}');background-size:cover;background-position:center;">
                    <div class="dine-card-overlay-label">
                        <div class="dine-pkg-name">${item.title}</div>
                        ${item.description ? `<div class="dine-pkg-desc">${item.description}</div>` : ''}
                        <div class="dine-card-tap-hint">Tap to reserve</div>
                    </div>
                </div>
                <div class="dine-slot-panel" id="dine-panel-${item.id}">
                    ${_buildDineSlotPanel(item)}
                </div>
            </div>`
    }

    function _buildDineSlotPanel(item) {
        const slots  = [item.slot1, item.slot2, item.slot3].filter(Boolean)
        const selIdx = dineSlots[item.id] !== undefined ? dineSlots[item.id] : -1
        const badges = slots.length
            ? slots.map((s, i) => `
                <button class="dine-slot-badge${i === selIdx ? ' selected' : ''}"
                        onclick="selectDineSlot(${item.id},${i},event)">${s}</button>`).join('')
            : '<span style="color:rgba(255,255,255,.3);font-size:11px;font-style:italic;">No slots available</span>'
        const btnLabel = selIdx >= 0 ? `Reserve ${slots[selIdx]}` : 'Reserve Table'
        return `
            <div class="dine-slots">${badges}</div>
            ${slots.length
                ? `<button class="dine-book-btn" id="dine-bookbtn-${item.id}"
                           onclick="openDineConfirm(${item.id});event.stopPropagation()">${btnLabel}</button>`
                : ''}`
    }

    window.toggleDineCard = function (itemId) {
        const card = document.getElementById('dine-card-' + itemId)
        if (!card) return
        const isOpen = card.classList.contains('expanded')
        if (dineExpandedId !== null && dineExpandedId !== itemId) {
            const prevCard = document.getElementById('dine-card-' + dineExpandedId)
            if (prevCard) prevCard.classList.remove('expanded')
        }
        if (isOpen) { card.classList.remove('expanded'); dineExpandedId = null }
        else         { card.classList.add('expanded');   dineExpandedId = itemId }
    }

    window.selectDineSlot = function (itemId, slotIdx, e) {
        e.stopPropagation()
        dineSlots[itemId] = slotIdx
        const card  = document.getElementById('dine-card-' + itemId)
        if (!card) return
        card.querySelectorAll('.dine-slot-badge').forEach((b, i) =>
            b.classList.toggle('selected', i === slotIdx))
        const item  = dineItems.find(i => i.id === itemId)
        const slots = [item.slot1, item.slot2, item.slot3].filter(Boolean)
        const btn   = document.getElementById('dine-bookbtn-' + itemId)
        if (btn) btn.textContent = `Reserve ${slots[slotIdx]}`
    }

    window.openDineConfirm = function (itemId) {
        const item = dineItems.find(i => i.id === itemId)
        if (!item) return
        const slots    = [item.slot1, item.slot2, item.slot3].filter(Boolean)
        const selIdx   = dineSlots[itemId] !== undefined ? dineSlots[itemId] : 0
        const slotTime = slots[selIdx] || slots[0] || '\u2014'
        dineSlots[itemId] = selIdx
        dinePending = { item, slotTime }

        const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val }
        set('dineConfirmName',  item.title)
        set('dineConfirmOcc',   item.occasion.charAt(0).toUpperCase() + item.occasion.slice(1))
        set('dineConfirmSlot',  slotTime)
        set('dineConfirmRoom',  'Room ' + (window.ROOM_NO || '\u2014'))

        const btn = document.getElementById('dineBookBtn')
        if (btn) { btn.textContent = 'Confirm Reservation'; btn.disabled = false; btn.style.background = '' }
        const overlay = document.getElementById('dineConfirmOverlay')
        if (overlay) overlay.classList.add('active')
    }

    window.closeDineConfirm = function () {
        const overlay = document.getElementById('dineConfirmOverlay')
        if (overlay) overlay.classList.remove('active')
    }

    window.confirmDineBooking = async function () {
        if (!dinePending) return
        const { item, slotTime } = dinePending
        const btn = document.getElementById('dineBookBtn')
        if (btn) { btn.disabled = true; btn.textContent = 'Reserving\u2026' }

        try {
            await fetch('/api/dine-booking', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    room_no:   window.ROOM_NO,
                    item_id:   item.id,
                    item_name: item.title,
                    occasion:  item.occasion,
                    slot:      slotTime,
                })
            }).catch(() => {})
        } catch (e) {}

        window.closeDineConfirm()
        dinePending = null

        const toast = document.getElementById('dineToast')
        if (toast) { toast.classList.add('show') }
        setTimeout(() => { if (toast) toast.classList.remove('show') }, 3000)
    }


    /* ═══════════════════════════════════════════════════════════════
       ENTERTAINMENT
    ═══════════════════════════════════════════════════════════════ */
    const ENT_CATEGORIES = [
        { id: 'indoor',   name: 'Indoor',   icon: '🎮', sub: 'Games, pools & more'        },
        { id: 'outdoor',  name: 'Outdoor',  icon: '⛷️', sub: 'Adventure & nature'          },
        { id: 'water',    name: 'Water',    icon: '🏊', sub: 'Pool & water sports'         },
        { id: 'kids',     name: 'Kids',     icon: '🎠', sub: 'Fun for the little ones'     },
        { id: 'night',    name: 'Night',    icon: '🌙', sub: 'Evening shows & experiences' },
    ]

    let entScreen   = 'categories'
    let entItems    = []
    let entPending  = null
    const entSlots  = {}
    let entExpandedId = null

    window.openEntMenu = async function () {
        const overlay = document.getElementById('entOverlay')
        if (!overlay) return
        overlay.classList.add('active')
        document.body.style.overflow = 'hidden'
        _showEntCategoryScreen()
        await _loadEntCategoryPreviews()
    }

    function _closeEntMenu() {
        const overlay = document.getElementById('entOverlay')
        if (overlay) overlay.classList.remove('active')
        document.body.style.overflow = ''
    }

    window.entGoBack = function () {
        if (entScreen === 'activities') _showEntCategoryScreen()
        else _closeEntMenu()
    }

    function _showEntCategoryScreen() {
        entScreen = 'categories'
        const catScreen = document.getElementById('entCategoryScreen')
        const actScreen = document.getElementById('entActivitiesScreen')
        const title     = document.getElementById('entPageTitle')
        const backLabel = document.getElementById('entBackLabel')
        if (catScreen) catScreen.style.display = 'flex'
        if (actScreen) actScreen.classList.remove('visible')
        if (title)     title.innerHTML = 'Entertainment'
        if (backLabel) backLabel.textContent = 'Home'
    }

    window.showEntActivitiesScreen = async function (catId, catName) {
        entScreen = 'activities'
        const catScreen = document.getElementById('entCategoryScreen')
        const actScreen = document.getElementById('entActivitiesScreen')
        const title     = document.getElementById('entPageTitle')
        const backLabel = document.getElementById('entBackLabel')
        const actLabel  = document.getElementById('entActivitiesLabel')
        const scroll    = document.getElementById('entActivitiesScroll')
        if (catScreen) catScreen.style.display = 'none'
        if (actScreen) actScreen.classList.add('visible')
        if (title)     title.innerHTML = catName + ' <em>Activities</em>'
        if (backLabel) backLabel.textContent = 'Categories'
        if (actLabel)  actLabel.textContent = catName.toUpperCase() + ' ACTIVITIES'
        if (scroll)    scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">Loading\u2026</div>'
        await _loadEntItems(catId)
    }

    async function _loadEntCategoryPreviews() {
        const grid = document.getElementById('entCatGrid')
        if (!grid) return

        grid.innerHTML = ENT_CATEGORIES.map(c => `
            <div class="ent-cat-card" id="ent-cat-${c.id}"
                 onclick="showEntActivitiesScreen('${c.id}','${c.name}')">
                <div class="ent-cat-img" id="ent-catimg-${c.id}"></div>
                <div class="ent-cat-body">
                    <div class="ent-cat-name">${c.icon} ${c.name}</div>
                    <div class="ent-cat-sub">${c.sub}</div>
                </div>
            </div>`).join('')

        let covers = {}
        try { covers = await fetch('/api/category-covers/entertainment').then(r => r.json()) } catch (e) {}

        await Promise.allSettled(ENT_CATEGORIES.map(async c => {
            const imgEl = document.getElementById('ent-catimg-' + c.id)
            if (!imgEl) return
            if (covers[c.id]) {
                imgEl.style.backgroundImage = `url('${covers[c.id]}')`
                imgEl.style.backgroundSize = 'cover'
                imgEl.style.backgroundPosition = 'center'
                return
            }
            try {
                const items = await fetch(`/api/entertainment-items?category=${c.id}`).then(r => r.json())
                if (items.length && items[0].image_url) {
                    imgEl.style.backgroundImage = `url('${items[0].image_url}')`
                    imgEl.style.backgroundSize = 'cover'
                    imgEl.style.backgroundPosition = 'center'
                }
                if (!items.length) {
                    const card = document.getElementById('ent-cat-' + c.id)
                    if (card) { card.style.opacity = '.4'; card.style.cursor = 'default'; card.onclick = null }
                }
            } catch (e) {}
        }))
    }

    async function _loadEntItems(catId) {
        const scroll = document.getElementById('entActivitiesScroll')
        try {
            entItems = await fetch(`/api/entertainment-items?category=${catId}`).then(r => r.json())
            _renderEntItems()
        } catch (e) {
            if (scroll) scroll.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">Failed to load.</div>'
        }
    }

    function _renderEntItems() {
        const el = document.getElementById('entActivitiesScroll')
        if (!el) return
        if (!entItems.length) {
            el.innerHTML = '<div style="color:rgba(248,243,236,.3);padding:40px;font-style:italic;grid-column:1/-1;">No activities in this category yet.</div>'
            return
        }
        entExpandedId = null
        el.innerHTML = entItems.map(item => _entActivityCard(item)).join('')
    }

    function _entActivityCard(item) {
        const cat = item.category.charAt(0).toUpperCase() + item.category.slice(1)
        const priceLabel = item.price ? `\u20b9${item.price}` : 'Free'
        return `
            <div class="ent-activity-card" id="ent-card-${item.id}"
                 onclick="toggleEntCard(${item.id})">
                <div class="ent-activity-bg" style="background-image:url('${item.image_url}');background-size:cover;background-position:center;">
                    <div class="ent-card-overlay-label">
                        <div class="ent-activity-name">${item.title}</div>
                        <div class="ent-activity-meta">
                            <span class="ent-activity-cat">${cat}</span>
                            <span class="ent-activity-price">${priceLabel}</span>
                        </div>
                        ${item.venue ? `<div class="ent-activity-venue">📍 ${item.venue}</div>` : ''}
                        <div class="ent-card-tap-hint">Tap to book</div>
                    </div>
                </div>
                <div class="ent-slot-panel" id="ent-panel-${item.id}">
                    ${_buildEntSlotPanel(item)}
                </div>
            </div>`
    }

    function _buildEntSlotPanel(item) {
        const slots  = [item.slot1, item.slot2, item.slot3].filter(Boolean)
        const selIdx = entSlots[item.id] !== undefined ? entSlots[item.id] : -1
        const priceLabel = item.price ? `\u20b9${item.price} / person` : 'Complimentary'
        const badges = slots.length
            ? slots.map((s, i) => `
                <button class="ent-slot-badge${i === selIdx ? ' selected' : ''}"
                        onclick="selectEntSlot(${item.id},${i},event)">${s}</button>`).join('')
            : '<span style="color:rgba(255,255,255,.3);font-size:11px;font-style:italic;">No slots available</span>'
        const btnLabel = selIdx >= 0 ? `Book ${slots[selIdx]}` : 'Book Slot'
        return `
            <div style="font-size:11px;color:var(--gold);letter-spacing:.15em;text-transform:uppercase;margin-bottom:8px;">${priceLabel}</div>
            ${item.venue ? `<div style="font-size:11px;color:rgba(248,243,236,.45);margin-bottom:10px;">📍 ${item.venue}</div>` : ''}
            <div class="ent-slots">${badges}</div>
            ${slots.length
                ? `<button class="ent-book-slot-btn" id="ent-bookbtn-${item.id}"
                           onclick="openEntConfirm(${item.id});event.stopPropagation()">${btnLabel}</button>`
                : ''}`
    }

    window.toggleEntCard = function (itemId) {
        const card = document.getElementById('ent-card-' + itemId)
        if (!card) return
        const isOpen = card.classList.contains('expanded')
        if (entExpandedId !== null && entExpandedId !== itemId) {
            const prev = document.getElementById('ent-card-' + entExpandedId)
            if (prev) prev.classList.remove('expanded')
        }
        if (isOpen) { card.classList.remove('expanded'); entExpandedId = null }
        else         { card.classList.add('expanded');   entExpandedId = itemId }
    }

    window.selectEntSlot = function (itemId, slotIdx, e) {
        e.stopPropagation()
        entSlots[itemId] = slotIdx
        const card  = document.getElementById('ent-card-' + itemId)
        if (!card) return
        card.querySelectorAll('.ent-slot-badge').forEach((b, i) =>
            b.classList.toggle('selected', i === slotIdx))
        const item  = entItems.find(i => i.id === itemId)
        const slots = [item.slot1, item.slot2, item.slot3].filter(Boolean)
        const btn   = document.getElementById('ent-bookbtn-' + itemId)
        if (btn) btn.textContent = `Book ${slots[slotIdx]}`
    }

    window.openEntConfirm = function (itemId) {
        const item = entItems.find(i => i.id === itemId)
        if (!item) return
        const slots    = [item.slot1, item.slot2, item.slot3].filter(Boolean)
        const selIdx   = entSlots[itemId] !== undefined ? entSlots[itemId] : 0
        const slotTime = slots[selIdx] || slots[0] || '\u2014'
        entSlots[itemId] = selIdx
        entPending = { item, slotTime }

        const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val }
        set('entConfirmName',  item.title)
        set('entConfirmCat',   item.category.charAt(0).toUpperCase() + item.category.slice(1))
        set('entConfirmSlot',  slotTime)
        set('entConfirmVenue', item.venue || '\u2014')
        set('entConfirmPrice', item.price ? `\u20b9${item.price} / person` : 'Complimentary')
        set('entConfirmRoom',  'Room ' + (window.ROOM_NO || '\u2014'))

        const btn = document.getElementById('entBookBtn')
        if (btn) { btn.textContent = 'Confirm Booking'; btn.disabled = false; btn.style.background = '' }
        const overlay = document.getElementById('entConfirmOverlay')
        if (overlay) overlay.classList.add('active')
    }

    window.closeEntConfirm = function () {
        const overlay = document.getElementById('entConfirmOverlay')
        if (overlay) overlay.classList.remove('active')
        entPending = null
    }

    window.confirmEntBooking = async function () {
        if (!entPending) return
        const btn = document.getElementById('entBookBtn')
        if (btn) { btn.disabled = true; btn.textContent = 'Booking\u2026' }
        try {
            await fetch('/api/entertainment-booking', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    room_no:    window.ROOM_NO,
                    item_id:    entPending.item.id,
                    item_title: entPending.item.title,
                    category:   entPending.item.category,
                    slot:       entPending.slotTime,
                    guests:     1,
                })
            }).catch(() => {})
        } catch (e) {}
        window.closeEntConfirm()
        const toast = document.getElementById('entToast')
        if (toast) { toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 3000) }
    }


    /* ═══════════════════════════════════════════════════════════════
       MY ORDERS / MY BOOKINGS
    ═══════════════════════════════════════════════════════════════ */
    let _myOrdersPollTimer = null

    window.openMyOrders = function () {
        const overlay   = document.getElementById('myOrdersOverlay')
        const container = document.getElementById('myOrdersContent')
        if (!overlay) return
        overlay.classList.add('active')
        document.body.style.overflow = 'hidden'

        /* Show placeholder ONLY on first open when container is empty */
        if (container && !container.innerHTML.trim()) {
            container.innerHTML = '<p style="color:rgba(248,243,236,.3);text-align:center;padding:40px 0;font-style:italic;">Loading your bookings…</p>'
        }

        loadMyOrders()
        clearInterval(_myOrdersPollTimer)
        _myOrdersPollTimer = setInterval(loadMyOrders, 15000)
    }

    window.closeMyOrders = function () {
        const overlay = document.getElementById('myOrdersOverlay')
        if (overlay) overlay.classList.remove('active')
        document.body.style.overflow = ''
        clearInterval(_myOrdersPollTimer)
        _myOrdersPollTimer = null
    }

    async function loadMyOrders() {
        if (!window.ROOM_NO) return
        const overlay   = document.getElementById('myOrdersOverlay')
        const container = document.getElementById('myOrdersContent')
        if (!container) return

        /* Silent background poll — skip entirely if overlay is not visible */
        const overlayOpen = overlay && overlay.classList.contains('active')
        if (!overlayOpen) return

        /* NO "Loading…" flash — fetch silently in background, swap once done */
        try {
            const data = await fetch('/api/my-orders/' + window.ROOM_NO).then(r => r.json())
            /* Re-check overlay is still open after async fetch completes */
            if (overlay && overlay.classList.contains('active')) {
                container.innerHTML = _renderMyOrders(data)
            }
        } catch (e) {
            /* Silent fail on background poll — don't flash an error either */
        }
    }

    // ── Guest alert / toast helper ────────────────────────────────
    function _showOrderAlert(msg, color) {
        color = color || '#1abc9c'
        let toast = document.getElementById('_globalOrderToast')
        if (!toast) {
            toast = document.createElement('div')
            toast.id = '_globalOrderToast'
            toast.style.cssText = [
                'position:fixed;bottom:32px;left:50%;transform:translateX(-50%) translateY(20px)',
                'background:#1a0510;border:.5px solid rgba(212,168,67,.4)',
                'color:var(--cream,#f8f3ec);padding:14px 28px;border-radius:40px',
                'font-size:14px;font-weight:500;letter-spacing:.02em',
                'box-shadow:0 8px 32px rgba(0,0,0,.5);z-index:99999',
                'opacity:0;transition:opacity .35s,transform .35s;pointer-events:none'
            ].join(';')
            document.body.appendChild(toast)
        }
        toast.style.borderColor = color === '#e74c3c' ? 'rgba(231,76,60,.5)' : 'rgba(212,168,67,.4)'
        toast.textContent = msg
        toast.style.opacity = '1'
        toast.style.transform = 'translateX(-50%) translateY(0)'
        clearTimeout(toast._hideTimer)
        toast._hideTimer = setTimeout(() => {
            toast.style.opacity = '0'
            toast.style.transform = 'translateX(-50%) translateY(20px)'
        }, 3200)
    }

    function _moStatusBadge(status) {
        const styles = {
            pending:   'background:rgba(212,168,67,.2);color:var(--gold-light);border:.5px solid rgba(212,168,67,.4)',
            confirmed: 'background:rgba(26,188,156,.2);color:#1abc9c;border:.5px solid rgba(26,188,156,.4)',
            delivered: 'background:rgba(26,188,156,.3);color:#1abc9c;border:.5px solid rgba(26,188,156,.5)',
            completed: 'background:rgba(26,188,156,.3);color:#1abc9c;border:.5px solid rgba(26,188,156,.5)',
            cancelled: 'background:rgba(231,76,60,.15);color:#e74c3c;border:.5px solid rgba(231,76,60,.3)',
        }
        const s = styles[status] || 'background:rgba(255,255,255,.08);color:rgba(248,243,236,.5)'
        return '<span style="' + s + ';padding:2px 10px;border-radius:20px;font-size:10px;letter-spacing:.1em;text-transform:capitalize;">' + status + '</span>'
    }

    function _parseBookedAt(str) {
        if (!str || str === '—') return 0
        try { return new Date(str).getTime() || 0 } catch(e) { return 0 }
    }

    /**
     * FIXED: Determine booking status based on cancellation window expiration
     * If the booking is "pending" but the cancellation window has expired, return "confirmed"
     * Otherwise, return the original status
     */
    function _getActualStatus(originalStatus, bookedEpoch, cancellationWindowMs) {
        // If status is not "pending", return as-is
        if (originalStatus !== 'pending') {
            return originalStatus
        }
        
        // If no booking epoch, return pending (can't determine)
        if (!bookedEpoch) {
            return originalStatus
        }
        
        // Default cancellation window: 10 minutes = 600000 ms (must match backend)
        const window = cancellationWindowMs || 600000
        const now = Date.now()
        const cancelDeadline = bookedEpoch + window
        
        // If current time is PAST the cancellation deadline, mark as confirmed
        return (now > cancelDeadline) ? 'confirmed' : 'pending'
    }

    function _renderMyOrders(data) {
        const { totals, orders, spa_bookings, entertainment_bookings, activity_bookings, dine_bookings, meal_plan } = data
        let html = ''
        html += '<div style="background:rgba(212,168,67,.08);border:.5px solid rgba(212,168,67,.2);border-radius:14px;padding:18px 24px;margin-bottom:24px;display:flex;justify-content:space-between;align-items:center;">'
        html += '<div><div style="font-size:11px;letter-spacing:.3em;text-transform:uppercase;color:rgba(212,168,67,.6);margin-bottom:4px;">Total Charges So Far</div>'

        // Recalculate totals on the frontend using _getActualStatus so that
        // orders auto-confirmed after 10 mins are included in the grand total
        // rather than relying on server totals which still see them as "pending".
        const WIN = 600000 // 10 minutes — must match _getActualStatus calls below

        const calcFood = (orders||[])
            .filter(o => o.type === 'food' && o.status !== 'cancelled'
                      && _getActualStatus(o.status, o.booked_epoch || 0, WIN) === 'confirmed')
            .reduce((s, o) => s + (Number(o.total) || 0), 0)

        const calcBar = (orders||[])
            .filter(o => o.type === 'bar' && o.status !== 'cancelled'
                      && _getActualStatus(o.status, o.booked_epoch || 0, WIN) === 'confirmed')
            .reduce((s, o) => s + (Number(o.total) || 0), 0)

        const calcSpa = (spa_bookings||[])
            .filter(b => b.status !== 'cancelled'
                      && _getActualStatus(b.status, b.booked_epoch || 0, WIN) === 'confirmed')
            .reduce((s, b) => s + (Number(b.price) || 0), 0)

        const calcEnt = (entertainment_bookings||[])
            .filter(b => b.status !== 'cancelled'
                      && _getActualStatus(b.status, b.booked_epoch || 0, WIN) === 'confirmed')
            .reduce((s, b) => s + (Number(b.price) || 0), 0)

        const calcDine = (dine_bookings||[])
            .filter(b => b.status !== 'cancelled'
                      && _getActualStatus(b.status, b.booked_epoch || 0, WIN) === 'confirmed')
            .reduce((s, b) => s + (Number(b.price) || 0), 0)

        const calcGrand = calcFood + calcBar + calcSpa + calcEnt + calcDine

        html += '<div style="font-size:12px;color:rgba(248,243,236,.4);">Food ₹' + calcFood + ' · Bar ₹' + calcBar + ' · Spa ₹' + calcSpa + ' · Ent ₹' + calcEnt + ' · Dining ₹' + calcDine + '</div>'

        // Pending = items whose status is still genuinely pending (within 10-min window)
        const pendingFood = (orders||[]).filter(o => o.type === 'food' && _getActualStatus(o.status, o.booked_epoch || 0, WIN) === 'pending').reduce((s,o)=>s+(Number(o.total)||0),0)
        const pendingSpa  = (spa_bookings||[]).filter(b => _getActualStatus(b.status, b.booked_epoch || 0, WIN) === 'pending').reduce((s,b)=>s+(Number(b.price)||0),0)
        const pendingEnt  = (entertainment_bookings||[]).filter(b => _getActualStatus(b.status, b.booked_epoch || 0, WIN) === 'pending').reduce((s,b)=>s+(Number(b.price)||0),0)
        const pendingDine = (dine_bookings||[]).filter(b => _getActualStatus(b.status, b.booked_epoch || 0, WIN) === 'pending').reduce((s,b)=>s+(Number(b.price)||0),0)
        const pendingTotal = pendingFood + pendingSpa + pendingEnt + pendingDine
        if (pendingTotal > 0) html += '<div style="font-size:11px;color:rgba(212,168,67,.5);margin-top:4px;">+ \u20b9' + pendingTotal.toLocaleString('en-IN') + ' pending admin confirmation</div>'
        html += '</div>'
        html += '<div style="font-family:\'Cormorant Garamond\',serif;font-size:36px;font-weight:300;color:var(--gold-light);">₹' + calcGrand.toLocaleString('en-IN') + '</div></div>'

        // ── Meal Plan Box ─────────────────────────────────────────────────────
        const MEAL_LABELS = {
            'AI':  '🍽️ All Inclusive',
            'AP':  '🍳 Full Board',
            'MAP': '🥗 Half Board',
            'CP':  '☕ Breakfast Only',
            'EP':  '🛏️ Room Only',
        }
        html += '<div style="background:rgba(255,255,255,.05);border:.5px solid rgba(192,24,90,.2);border-radius:14px;padding:16px 22px;margin-bottom:22px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">'
        html += '<div><div style="font-size:10px;letter-spacing:.35em;text-transform:uppercase;color:rgba(212,168,67,.6);margin-bottom:5px;">Meal Plan</div>'
        html += '<div style="font-size:18px;font-weight:500;color:var(--cream);">' + (MEAL_LABELS[meal_plan] || '—') + '</div></div>'
        html += '<select onchange="changeMealPlan(this.value)" style="background:rgba(255,255,255,.08);border:.5px solid rgba(192,24,90,.4);color:var(--gold-light);border-radius:10px;padding:8px 14px;font-family:\'Jost\',sans-serif;font-size:13px;outline:none;cursor:pointer;">'
        html += '<option value="">Change plan…</option>'
        html += '<option value="AI"'  + (meal_plan === 'AI'  ? ' selected' : '') + '>All Inclusive (AI)</option>'
        html += '<option value="AP"'  + (meal_plan === 'AP'  ? ' selected' : '') + '>Full Board (AP)</option>'
        html += '<option value="MAP"' + (meal_plan === 'MAP' ? ' selected' : '') + '>Half Board (MAP)</option>'
        html += '<option value="CP"'  + (meal_plan === 'CP'  ? ' selected' : '') + '>Breakfast Only (CP)</option>'
        html += '<option value="EP"'  + (meal_plan === 'EP'  ? ' selected' : '') + '>Room Only (EP)</option>'
        html += '</select></div>'
        // ─────────────────────────────────────────────────────────────────────

        const noContent = !orders.length && !spa_bookings.length && !entertainment_bookings.length && !activity_bookings.length && !dine_bookings.length
        if (noContent) {
            html += '<p style="color:rgba(248,243,236,.25);text-align:center;padding:40px 0;font-style:italic;font-size:15px;">No bookings yet.<br>Explore our services to get started.</p>'
            return html
        }

        function section(title) {
            return '<div style="font-size:10px;letter-spacing:.4em;text-transform:uppercase;color:var(--gold);margin:22px 0 10px;display:flex;align-items:center;gap:10px;">' + title + '<span style="flex:1;height:.5px;background:linear-gradient(90deg,rgba(212,168,67,.3),transparent);"></span></div>'
        }

        function card(left, right, meta, cancelType, cancelId, bookedEpoch) {
            const now          = Date.now()
            const withinWindow = bookedEpoch && (now - bookedEpoch) < 600000
            const cancelBtn    = (cancelType && cancelId && withinWindow)
                ? `<button onclick="guestCancel('${cancelType}',${cancelId},this)"
                       style="margin-top:8px;padding:4px 14px;border-radius:20px;font-size:11px;font-weight:600;
                              background:rgba(231,76,60,.12);color:#e74c3c;border:.5px solid rgba(231,76,60,.4);
                              cursor:pointer;letter-spacing:.04em;">❌ Cancel</button>`
                : (cancelType && cancelId && !withinWindow && right.includes('pending'))
                ? `<span style="font-size:10px;color:rgba(248,243,236,.25);margin-top:6px;display:block;">Cancel window expired</span>`
                : ''
            return '<div style="background:rgba(20,4,12,0.72);border:.5px solid rgba(192,24,90,.15);border-radius:12px;padding:14px 18px;margin-bottom:10px;">'
                + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
                + '<span style="font-size:14px;color:var(--cream);font-weight:500;">' + left + '</span>' + right
                + '</div>'
                + '<div style="font-size:11px;color:rgba(248,243,236,.35);">' + meta + '</div>'
                + cancelBtn
                + '</div>'
        }

        const foodOrders = (orders||[]).filter(o => o.type === 'food' && o.status !== 'cancelled')
        if (foodOrders.length) {
            html += section('Room Service')
            foodOrders.forEach(o => {
                let items = []
                try { items = JSON.parse(o.items.replace(/'/g, '"')) } catch(e) {}
                const label = items.length ? items.map(i => i.name + ' x' + i.qty).join(', ') : 'Order #' + o.id
                const actualStatus = _getActualStatus(o.status, o.booked_epoch || 0, WIN)
                html += card(label, _moStatusBadge(actualStatus), '₹' + o.total + ' · ' + o.ordered_at, 'order', o.id, o.booked_epoch || 0)
            })
        }
        const barOrders = (orders||[]).filter(o => o.type === 'bar' && o.status !== 'cancelled')
        if (barOrders.length) {
            html += section('Bar Orders')
            barOrders.forEach(o => {
                let items = []
                try { items = JSON.parse(o.items.replace(/'/g, '"')) } catch(e) {}
                const label = items.length ? items.map(i => i.name + ' x' + i.qty).join(', ') : 'Bar Order #' + o.id
                const actualStatus = _getActualStatus(o.status, o.booked_epoch || 0, WIN)
                html += card(label, _moStatusBadge(actualStatus), '₹' + o.total + ' · ' + o.ordered_at, 'order', o.id, o.booked_epoch || 0)
            })
        }
        const visibleSpa = (spa_bookings||[]).filter(b => b.status !== 'cancelled')
        if (visibleSpa.length) {
            html += section('Spa & Wellness')
            visibleSpa.forEach(b => {
                const priceStr = b.price && b.price > 0 ? ' · ₹' + b.price : ''
                const actualStatus = _getActualStatus(b.status, b.booked_epoch || 0, WIN)
                html += card(b.title, _moStatusBadge(actualStatus), b.slot + priceStr + ' · ' + b.booked_at, 'spa', b.id, b.booked_epoch || 0)
            })
        }
        const visibleEnt = (entertainment_bookings||[]).filter(b => b.status !== 'cancelled')
        if (visibleEnt.length) {
            html += section('Entertainment')
            visibleEnt.forEach(b => {
                const meta = [b.slot, b.venue, b.price ? '₹' + b.price : null, b.booked_at].filter(Boolean).join(' · ')
                const actualStatus = _getActualStatus(b.status, b.booked_epoch || 0, WIN)
                html += card(b.title + (b.guests > 1 ? ' x' + b.guests : ''), _moStatusBadge(actualStatus), meta, 'entertainment', b.id, b.booked_epoch || 0)
            })
        }
        const visibleAct = (activity_bookings||[]).filter(b => b.status !== 'cancelled')
        if (visibleAct.length) {
            html += section('Activity Reservations')
            visibleAct.forEach(b => {
                const actualStatus = _getActualStatus(b.status, b.booked_epoch || 0, WIN)
                html += card(b.title, _moStatusBadge(actualStatus), [b.time_slot, b.booked_at].filter(Boolean).join(' · '), 'activity', b.id, b.booked_epoch || 0)
            })
        }
        const visibleDine = (dine_bookings||[]).filter(b => b.status !== 'cancelled')
        if (visibleDine.length) {
            html += section('Dining Reservations')
            visibleDine.forEach(b => {
                const actualStatus = _getActualStatus(b.status, b.booked_epoch || 0, WIN)
                html += card(b.title, _moStatusBadge(actualStatus), b.slot + ' · ' + b.booked_at, 'dine', b.id, b.booked_epoch || 0)
            })
        }

        return html  // BUG FIX: missing return statement — function never returned html
    }


    /* ═══════════════════════════════════════════════════════════════
       GALLERY
    ═══════════════════════════════════════════════════════════════ */
    let _galleryItems = []

    window.openGalleryMenu = async function () {
        const overlay = document.getElementById('galleryOverlay')
        if (!overlay) return
        overlay.classList.add('active')
        document.body.style.overflow = 'hidden'
        await _renderGallery()
    }

    function _closeGalleryMenu() {
        const overlay = document.getElementById('galleryOverlay')
        if (overlay) overlay.classList.remove('active')
        document.body.style.overflow = ''
    }

    window.galleryGoBack = function () { _closeGalleryMenu() }

    async function _renderGallery() {
        const grid = document.getElementById('galleryGrid')
        if (!grid) return

        grid.innerHTML = `<div class="gallery-loading">Loading gallery…</div>`

        try {
            const items = await fetch('/api/gallery-items').then(r => r.json())

            if (!items || !items.length) {
                grid.innerHTML = `<div class="gallery-loading">Gallery coming soon.</div>`
                return
            }

            _galleryItems = items

            grid.innerHTML = items.map((item, idx) => `
                <div class="gallery-thumb"
                     style="background-image:url('${item.image_url || ''}');"
                     onclick="openGalleryLightbox(${idx})">
                    <div class="gallery-thumb-info">
                        <div class="gallery-thumb-number">${String(idx + 1).padStart(2, '0')} · Vibe Munnar</div>
                        <div class="gallery-thumb-title">${item.title || ''}</div>
                        <div class="gallery-thumb-desc">${item.description || ''}</div>
                        <div class="gallery-thumb-accent"></div>
                    </div>
                </div>`).join('')

        } catch (e) {
            grid.innerHTML = `<div class="gallery-loading">Failed to load gallery. Please try again.</div>`
        }
    }

    window.openGalleryLightbox = function (idx) {
        const item = _galleryItems[idx]
        if (!item) return

        const lb = document.getElementById('galleryLightbox')
        if (!lb) return

        const img  = document.getElementById('glbImg')
        const num  = document.getElementById('glbNumber')
        const titl = document.getElementById('glbTitle')
        const desc = document.getElementById('glbDesc')

        if (img)  { img.src = item.image_url || ''; img.alt = item.title || '' }
        if (num)  num.textContent  = String(idx + 1).padStart(2, '0') + ' · Vibe Munnar'
        if (titl) titl.textContent = item.title || ''
        if (desc) desc.textContent = item.description || ''

        lb.classList.add('active')
    }

    window.closeGalleryLightbox = function () {
        const lb = document.getElementById('galleryLightbox')
        if (lb) lb.classList.remove('active')
    }


    /* ═══════════════════════════════════════════════════════════════
       ROOM SERVICE
    ═══════════════════════════════════════════════════════════════ */
    window._rsItemsMap = {}
    let rsPending = null

    window.openRoomServiceMenu = async function () {
        const overlay = document.getElementById('roomServiceOverlay')
        if (!overlay) return
        overlay.classList.add('active')
        document.body.style.overflow = 'hidden'
        await _renderRoomServices()
    }

    function _closeRoomServiceMenu() {
        const overlay = document.getElementById('roomServiceOverlay')
        if (overlay) overlay.classList.remove('active')
        document.body.style.overflow = ''
    }

    window.roomServiceGoBack = function () { _closeRoomServiceMenu() }
    window.rsGoBack          = function () { _closeRoomServiceMenu() }

    async function _renderRoomServices() {
        const grid = document.getElementById('rsGrid')
        if (!grid) return

        grid.innerHTML = `<div class="rs-loading">Loading services\u2026</div>`

        try {
            const items = await fetch('/api/room-service-items').then(r => r.json())

            if (!items || !items.length) {
                grid.innerHTML = `<div class="rs-loading">No services available right now.</div>`
                return
            }

            window._rsItemsMap = {}
            items.forEach(i => { window._rsItemsMap[i.id] = i })

            grid.innerHTML = items.map(s => `
                <div class="rs-card" onclick="openRsConfirm(${s.id})">
                    <div class="rs-card-img" style="background-image:url('${s.image_url || ''}');"></div>
                    <div class="rs-card-arrow">\u203a</div>
                    <div class="rs-card-body">
                        <span class="rs-card-icon">${s.icon || '\uD83D\uDECE\uFE0F'}</span>
                        <div class="rs-card-title">${s.title}</div>
                        <div class="rs-card-desc">${s.description || ''}</div>
                    </div>
                </div>`).join('')

        } catch (e) {
            grid.innerHTML = `<div class="rs-loading">Failed to load services. Please try again.</div>`
        }
    }

    window.openRsConfirm = function (serviceId) {
        const svc = window._rsItemsMap[serviceId]
        if (!svc) return
        rsPending = { id: svc.id, icon: svc.icon || '\uD83D\uDECE\uFE0F', title: svc.title }

        const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val }
        set('rsConfirmIcon',        rsPending.icon)
        set('rsConfirmTitle',       svc.title)
        set('rsConfirmTitleDetail', svc.title)
        set('rsConfirmDesc',        svc.description || 'Our team will attend to your request shortly.')
        set('rsConfirmRoom',        'Room ' + (window.ROOM_NO || '\u2014'))

        const note = document.getElementById('rsGuestNote') || document.getElementById('rsConfirmNote')
        if (note) note.value = ''

        const btn = document.getElementById('rsSendBtn') || document.getElementById('rsConfirmBtn')
        if (btn) { btn.textContent = 'Send Request'; btn.disabled = false; btn.style.background = '' }

        const modal = document.getElementById('rsConfirmOverlay')
        if (modal) modal.classList.add('active')
    }

    window.closeRsConfirm = function () {
        const modal = document.getElementById('rsConfirmOverlay')
        if (modal) modal.classList.remove('active')
        const note = document.getElementById('rsGuestNote') || document.getElementById('rsConfirmNote')
        if (note) note.value = ''
        rsPending = null
    }

    window.confirmRsRequest = async function () {
        if (!rsPending) return
        const noteEl  = document.getElementById('rsGuestNote') || document.getElementById('rsConfirmNote')
        const noteVal = noteEl ? noteEl.value.trim() : ''
        const btn     = document.getElementById('rsSendBtn') || document.getElementById('rsConfirmBtn')

        if (btn) { btn.disabled = true; btn.textContent = 'Sending\u2026' }
        try {
            await fetch('/api/room-service-request', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    room_no:       window.ROOM_NO,
                    service_id:    rsPending.id,
                    service_title: rsPending.title,
                    note:          noteVal,
                })
            }).catch(() => {})
        } catch (e) {}

        window.closeRsConfirm()
        const toast = document.getElementById('rsToast')
        if (toast) { toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 3500) }
    }


    /* ═══════════════════════════════════
       INIT — run everything on DOM ready
    ═══════════════════════════════════ */
    function init() {
        tickClock()
        setInterval(tickClock, 10000)

        loadRoomData()
        setInterval(loadRoomData, 5000)

        loadActivities()
        setInterval(loadActivities, 10000)

        loadServices()
        setInterval(loadServices, 30000)

        /* loadMyOrders polling is handled entirely by openMyOrders/closeMyOrders.
           Do NOT call loadMyOrders() here or set a global interval — the function
           checks overlay visibility anyway, but the old unguarded interval was the
           source of the visible "Loading your bookings…" flash every 30 s. */

        // Gallery lightbox — close on background click or Escape key
        const lb = document.getElementById('galleryLightbox')
        if (lb) {
            lb.addEventListener('click', function (e) {
                if (e.target === lb) window.closeGalleryLightbox()
            })
        }
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') window.closeGalleryLightbox()
        })
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init)
    } else {
        init()
    }

    /* ═══════════════════════════════════════════════════════════════
       ADMIN — ACTIVITIES (timepicker + toggleTimeSlot + deleteActivity)
       Fixes double AM/PM bug: strips any existing meridiem from the
       start-time string before arithmetic, then appends it once.
    ═══════════════════════════════════════════════════════════════ */

    /**
     * Parse a time string that may or may not contain AM/PM.
     * Returns { totalMinutes, h24 } so we can do arithmetic cleanly.
     */
    function _parseTime(str) {
        if (!str) return null
        // Normalise: remove extra spaces, upper-case
        str = str.trim().toUpperCase()

        // Detect and strip meridiem
        let meridiem = null
        if (str.endsWith('AM')) { meridiem = 'AM'; str = str.slice(0, -2).trim() }
        else if (str.endsWith('PM')) { meridiem = 'PM'; str = str.slice(0, -2).trim() }

        // Parse HH:MM or H:MM
        const parts = str.split(':')
        if (parts.length < 2) return null
        let h = parseInt(parts[0], 10)
        const m = parseInt(parts[1], 10)
        if (isNaN(h) || isNaN(m)) return null

        // Convert to 24-hour
        if (meridiem === 'AM') {
            if (h === 12) h = 0          // 12:xx AM → 00:xx
        } else if (meridiem === 'PM') {
            if (h !== 12) h += 12        // 1-11 PM → 13-23; 12 PM stays 12
        }
        // If no meridiem was present we treat the value as already 24-hour
        return { totalMinutes: h * 60 + m }
    }

    /** Format total minutes (0-1439) as "hh:mm AM/PM" — meridiem appears exactly once. */
    function _formatTime12(totalMinutes) {
        // Wrap around midnight
        totalMinutes = ((totalMinutes % 1440) + 1440) % 1440
        const h24 = Math.floor(totalMinutes / 60)
        const m   = totalMinutes % 60
        const mer = h24 < 12 ? 'AM' : 'PM'
        let h12   = h24 % 12
        if (h12 === 0) h12 = 12
        return String(h12).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ' ' + mer
    }

    /** Show/hide the time-slot block when the Announcement checkbox is toggled. */
    window.toggleTimeSlot = function () {
        const chk   = document.getElementById('is_announcement_check')
        const group = document.getElementById('timeslot-group')
        if (!group) return
        if (chk && chk.checked) {
            group.style.display = 'none'
        } else {
            group.style.display = 'flex'
        }
    }

    /** Delete an activity row and refresh the list. */
    window.deleteActivity = async function (id) {
        if (!confirm('Delete this activity?')) return
        try {
            await fetch('/admin/activities/delete/' + id, { method: 'POST' })
            window.location.reload()
        } catch (e) {
            alert('Could not delete activity. Please try again.')
        }
    }

    /* ── Activities admin: single-slot flatpickr ── */
    document.addEventListener('DOMContentLoaded', function () {
        const startEl    = document.querySelector('.act-slot-start[data-slot="1"]')
        const durationEl = document.querySelector('.act-slot-duration[data-slot="1"]')
        const endEl      = document.querySelector('.act-slot-end[data-slot="1"]')

        if (!startEl || !durationEl || !endEl) return

        // _actRecomputeEnd: called with the confirmed dateStr from flatpickr
        // OR with no arg to re-read startEl.value (duration change case)
        function _actRecomputeEnd(startStr) {
            const str    = (startStr !== undefined) ? startStr : startEl.value
            const parsed = _parseTime(str)
            if (!parsed) { endEl.value = ''; return }
            const duration = parseInt(durationEl.value, 10) || 60
            endEl.value = _formatTime12(parsed.totalMinutes + duration)
        }

        // Initialise flatpickr — use dateStr arg so value is always finalised
        if (typeof flatpickr !== 'undefined') {
            flatpickr(startEl, {
                enableTime:     true,
                noCalendar:     true,
                dateFormat:     'h:i K',       // e.g. "02:30 PM"
                minuteIncrement: 15,
                onChange: function (selectedDates, dateStr) {
                    _actRecomputeEnd(dateStr)
                }
            })
        } else {
            // fallback: plain input event
            startEl.addEventListener('change', function () { _actRecomputeEnd() })
        }

        durationEl.addEventListener('change', function () { _actRecomputeEnd() })

        // On submit: validate Slot 1 has a start time, then write
        // the combined "Start - End" string into the slot1 hidden field
        const form = startEl.closest('form')
        if (form) {
            form.addEventListener('submit', function (e) {
                const chk = document.getElementById('is_announcement_check')
                if (chk && chk.checked) return   // announcements skip slots

                const startVal = startEl.value.trim()
                if (!startVal) {
                    e.preventDefault()
                    startEl.focus()
                    alert('Please set a start time for Slot 1.')
                    return
                }

                // Write "HH:MM AM - HH:MM PM" into the slot1 field
                const slot1Input = form.querySelector('input[name="slot1"]')
                if (slot1Input) {
                    const endVal = endEl.value.trim()
                    slot1Input.value = endVal ? startVal + ' - ' + endVal : startVal
                }
            })
        }
    })

    /* ═══════════════════════════════════════════════════════════════
       MEAL PLAN — guest can change their meal plan from My Orders
       (from common1.js — new function not previously in common.js)
    ═══════════════════════════════════════════════════════════════ */
    window.changeMealPlan = async function (plan) {
        if (!plan) return
        try {
            const res = await fetch('/api/update-meal-plan', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ room_no: window.ROOM_NO, meal_plan: plan })
            })
            if (res.ok) {
                const toast = document.getElementById('actToast')
                if (toast) {
                    toast.textContent = '✓ Meal plan updated!'
                    toast.classList.add('show')
                    setTimeout(() => {
                        toast.classList.remove('show')
                        toast.textContent = '✓ Reserved! See you at the activity 🎉'
                    }, 3000)
                }
                loadMyOrders()
            }
        } catch (e) {
            console.error('Meal plan update failed:', e)
        }
    }

    window.guestCancel = function(type, id, btn) {
        // Show custom in-page confirmation modal instead of browser confirm()
        var overlay = document.getElementById('cancelConfirmOverlay')
        if (!overlay) return

        // Store pending cancel details on the overlay for use when confirmed
        overlay._pendingType = type
        overlay._pendingId   = id
        overlay._pendingBtn  = btn
        overlay.classList.add('active')
    }

    window._executeCancelBooking = async function() {
        var overlay = document.getElementById('cancelConfirmOverlay')
        if (!overlay) return
        var type = overlay._pendingType
        var id   = overlay._pendingId
        var btn  = overlay._pendingBtn
        overlay.classList.remove('active')

        if (btn) { btn.disabled = true; btn.textContent = 'Cancelling…' }
        try {
            const res  = await fetch('/api/cancel/' + type + '/' + id, { method: 'POST' })
            const data = await res.json()
            if (data.status === 'success') {
                _showOrderAlert('Booking cancelled successfully.', '#e74c3c')
                loadMyOrders()
            } else {
                _showOrderAlert(data.message || 'Could not cancel.', '#e74c3c')
                if (btn) { btn.disabled = false; btn.textContent = '❌ Cancel' }
            }
        } catch(e) {
            _showOrderAlert('Network error. Try again.', '#e74c3c')
            if (btn) { btn.disabled = false; btn.textContent = '❌ Cancel' }
        }
    }

    window.closeCancelConfirm = function() {
        var overlay = document.getElementById('cancelConfirmOverlay')
        if (overlay) overlay.classList.remove('active')
    }

    window.loadMyOrders   = loadMyOrders
    window.loadServices   = loadServices
    window.loadActivities = loadActivities
    window.loadRoomData   = loadRoomData

})()