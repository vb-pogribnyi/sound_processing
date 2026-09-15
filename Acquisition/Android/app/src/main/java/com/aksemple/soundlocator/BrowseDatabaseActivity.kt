package com.aksemple.soundlocator

import android.content.pm.ActivityInfo
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aksemple.soundlocator.ui.theme.SoundLocatorTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.pow

private const val PAGE_SIZE = 15
private const val DEFAULT_VISIBLE_CHANNELS = 4

// Distinct, light-theme-friendly colors, cycled for arbitrary channel counts.
private val channelPalette = listOf(
    Color(0xFFD32F2F), Color(0xFF388E3C), Color(0xFF1976D2), Color(0xFFF57C00),
    Color(0xFF7B1FA2), Color(0xFF0097A7), Color(0xFFC2185B), Color(0xFF5D4037),
)
private fun channelColor(ch: Int): Color = channelPalette[((ch % channelPalette.size) + channelPalette.size) % channelPalette.size]

class BrowseDatabaseActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        setContent {
            SoundLocatorTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    // A fresh composition on each entry -> the checkbox selection below
                    // starts empty every time the activity is opened.
                    BrowseDatabaseScreen()
                }
            }
        }
    }
}

@Composable
private fun BrowseDatabaseScreen() {
    val context = LocalContext.current
    val db = remember { AppDatabase.getInstance(context) }
    val scope = rememberCoroutineScope()

    val captures = remember { mutableStateListOf<CaptureListItem>() }
    var isLoading by remember { mutableStateOf(false) }
    var endReached by remember { mutableStateOf(false) }

    // Checked capture ids. Fresh (empty) on every entry into the activity.
    val checkedIds = remember { mutableStateListOf<Long>() }
    // Visualization spans the inclusive id range [min checked .. max checked]; ALL
    // captures in that range are concatenated in arrival order, checked or not.
    val rangeMin = checkedIds.minOrNull()
    val rangeMax = checkedIds.maxOrNull()
    val hasRange = rangeMin != null && rangeMax != null
    val rangeKey = "${rangeMin ?: -1}-${rangeMax ?: -1}"
    val rangeNChannels = remember(captures.size, rangeKey) {
        captures.firstOrNull { it.id in checkedIds }?.nChannels ?: 0
    }

    // Concatenated per-channel data for the current range, loaded lazily per channel.
    val channelData = remember { mutableStateMapOf<Int, IntArray>() }
    var boundaries by remember { mutableStateOf(IntArray(0)) }   // sample indices where captures join
    val checkedChannels = remember { mutableStateListOf<Int>() }
    var waveLoading by remember { mutableStateOf(false) }
    var loadedRange by remember { mutableStateOf<Pair<Long, Long>?>(null) }

    fun reloadForRange() {
        val lo = checkedIds.minOrNull()
        val hi = checkedIds.maxOrNull()
        if (lo == null || hi == null) {
            channelData.clear(); boundaries = IntArray(0); loadedRange = null; waveLoading = false
            return
        }
        val nCh = captures.firstOrNull { it.id in checkedIds }?.nChannels ?: 1
        if (checkedChannels.isEmpty()) {
            checkedChannels.addAll(0 until minOf(DEFAULT_VISIBLE_CHANNELS, nCh))
        } else {
            checkedChannels.retainAll { it < nCh }
        }
        val range = lo to hi
        loadedRange = range
        channelData.clear()
        waveLoading = true
        scope.launch {
            try {
                // Boundaries from channel 0 (per-capture sample counts are equal across channels).
                val counts = withContext(Dispatchers.IO) { db.soundDataDao().channelCountsInRange(lo, hi, 0) }
                val bnds = ArrayList<Int>()
                var acc = 0
                for (i in 0 until (counts.size - 1)) { acc += counts[i].cnt; bnds.add(acc) }
                if (loadedRange == range) boundaries = bnds.toIntArray()
                for (ch in checkedChannels.toList()) {
                    val vals = withContext(Dispatchers.IO) {
                        db.soundDataDao().loadChannelRange(lo, hi, ch).map { it.value }.toIntArray()
                    }
                    if (loadedRange == range) channelData[ch] = vals
                }
            } catch (e: Exception) {
                android.util.Log.e("BrowseDatabase", "Failed to load range $lo..$hi", e)
            } finally {
                if (loadedRange == range) waveLoading = false
            }
        }
    }

    fun toggleCapture(id: Long) {
        if (checkedIds.contains(id)) checkedIds.remove(id) else checkedIds.add(id)
        val lo = checkedIds.minOrNull()
        val hi = checkedIds.maxOrNull()
        val newRange = if (lo != null && hi != null) lo to hi else null
        if (newRange != loadedRange) reloadForRange()   // only reload when the span actually changes
    }

    fun toggleChannel(ch: Int) {
        val range = loadedRange ?: return
        if (checkedChannels.contains(ch)) {
            checkedChannels.remove(ch)
        } else {
            checkedChannels.add(ch)
            if (!channelData.containsKey(ch)) {
                scope.launch {
                    try {
                        val vals = withContext(Dispatchers.IO) {
                            db.soundDataDao().loadChannelRange(range.first, range.second, ch).map { it.value }.toIntArray()
                        }
                        if (loadedRange == range) channelData[ch] = vals
                    } catch (e: Exception) {
                        android.util.Log.e("BrowseDatabase", "Failed to load channel $ch", e)
                    }
                }
            }
        }
    }

    fun loadNextPage() {
        if (isLoading || endReached) return
        isLoading = true
        scope.launch {
            try {
                val page = withContext(Dispatchers.IO) {
                    db.capturesDao().getCapturesPaged(PAGE_SIZE, captures.size)
                }
                captures.addAll(page)
                if (page.size < PAGE_SIZE) endReached = true
            } catch (e: Exception) {
                android.util.Log.e("BrowseDatabase", "Failed to load captures page", e)
                endReached = true
            } finally {
                isLoading = false
            }
        }
    }

    LaunchedEffect(Unit) { loadNextPage() }

    Row(modifier = Modifier.fillMaxSize()) {
        Box(modifier = Modifier.weight(2f).fillMaxHeight()) {
            WaveformPane(
                hasSelection = hasRange,
                nChannels = rangeNChannels,
                rangeKey = rangeKey,
                channelData = channelData,
                boundaries = boundaries,
                checkedChannels = checkedChannels,
                loading = waveLoading,
                onToggleChannel = { toggleChannel(it) }
            )
        }
        VerticalDivider(
            modifier = Modifier.fillMaxHeight(),
            color = MaterialTheme.colorScheme.outlineVariant
        )
        Box(modifier = Modifier.weight(1f).fillMaxHeight()) {
            CaptureListPane(
                captures = captures,
                checkedIds = checkedIds,
                rangeMin = rangeMin,
                rangeMax = rangeMax,
                isLoading = isLoading,
                endReached = endReached,
                onLoadMore = { loadNextPage() },
                onToggle = { toggleCapture(it) }
            )
        }
    }
}

@Composable
private fun CaptureListPane(
    captures: List<CaptureListItem>,
    checkedIds: List<Long>,
    rangeMin: Long?,
    rangeMax: Long?,
    isLoading: Boolean,
    endReached: Boolean,
    onLoadMore: () -> Unit,
    onToggle: (Long) -> Unit,
) {
    val listState = rememberLazyListState()

    LaunchedEffect(listState, captures.size, endReached) {
        snapshotFlow {
            listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
        }.distinctUntilChanged().collect { lastVisible ->
            if (!endReached && lastVisible >= captures.size - 3) onLoadMore()
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        Text(
            text = "Captures — check a range to plot",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(12.dp)
        )
        HorizontalDivider()
        LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
            items(items = captures, key = { it.id }) { item ->
                val inRange = rangeMin != null && rangeMax != null && item.id in rangeMin..rangeMax
                CaptureRow(
                    item = item,
                    checked = checkedIds.contains(item.id),
                    inRange = inRange,
                    onToggle = { onToggle(item.id) }
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
            }
            if (isLoading || !endReached) {
                item {
                    Box(
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(modifier = Modifier.size(24.dp))
                    }
                }
            }
            if (endReached && captures.isEmpty()) {
                item {
                    Box(
                        modifier = Modifier.fillMaxWidth().padding(24.dp),
                        contentAlignment = Alignment.Center
                    ) { Text("No captures in database") }
                }
            }
        }
    }
}

private val dateFormat = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault())

@Composable
private fun CaptureRow(item: CaptureListItem, checked: Boolean, inRange: Boolean, onToggle: () -> Unit) {
    val bg = when {
        checked -> MaterialTheme.colorScheme.primaryContainer
        inRange -> MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.4f)
        else -> Color.Transparent
    }
    val perChannel = if (item.nChannels > 0) item.soundCount / item.nChannels else item.soundCount
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(bg)
            .clickable(onClick = onToggle)
            .padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Checkbox(checked = checked, onCheckedChange = { onToggle() })
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = dateFormat.format(Date(item.timestamp)),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = "#${item.id}  ·  ${item.nChannels} ch × $perChannel",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                if (item.isOverrun != 0) {
                    Text(
                        text = "overrun: ${item.isOverrun}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
        }
    }
}

@Composable
private fun WaveformPane(
    hasSelection: Boolean,
    nChannels: Int,
    rangeKey: String,
    channelData: Map<Int, IntArray>,
    boundaries: IntArray,
    checkedChannels: List<Int>,
    loading: Boolean,
    onToggleChannel: (Int) -> Unit,
) {
    if (!hasSelection) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                "Check one or more captures — the range (first→last) is plotted in arrival order",
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        return
    }

    val visible = checkedChannels.filter { channelData.containsKey(it) }.sorted()
    val visibleKey = visible.joinToString(",")

    // n = total samples per channel across the range; y-range over visible channels.
    val stats = remember(rangeKey, visibleKey, channelData.size) {
        var n = 0
        var mn = Int.MAX_VALUE
        var mx = Int.MIN_VALUE
        for (ch in visible) {
            val arr = channelData[ch] ?: continue
            if (arr.size > n) n = arr.size
            for (v in arr) {
                if (v < mn) mn = v
                if (v > mx) mx = v
            }
        }
        if (n == 0) { mn = 0; mx = 1 }
        if (mn == mx) { mn -= 1; mx += 1 }
        Triple(n, mn.toFloat(), mx.toFloat())
    }
    val n = stats.first
    val yMin = stats.second
    val yMax = stats.third

    // Reset the view whenever the selected range changes.
    var scale by remember(rangeKey) { mutableFloatStateOf(1f) }
    var offset by remember(rangeKey) { mutableStateOf(Offset.Zero) }

    val textMeasurer = rememberTextMeasurer()
    val axisColor = MaterialTheme.colorScheme.outline
    val gridColor = MaterialTheme.colorScheme.outlineVariant
    val labelColor = MaterialTheme.colorScheme.onSurfaceVariant
    val boundaryColor = Color(0x66000000)
    val labelStyle = TextStyle(color = labelColor, fontSize = 10.sp)

    Box(modifier = Modifier.fillMaxSize()) {
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .pointerInput(rangeKey) {
                    detectTransformGestures { centroid, pan, zoom, _ ->
                        val newScale = (scale * zoom).coerceIn(0.25f, 5000f)
                        offset = centroid + pan - (centroid - offset) * (newScale / scale)
                        scale = newScale
                    }
                }
        ) {
            val marginLeft = 68f
            val marginBottom = 44f
            val marginTop = 16f
            val marginRight = 16f
            val plotW = (size.width - marginLeft - marginRight).coerceAtLeast(1f)
            val plotH = (size.height - marginTop - marginBottom).coerceAtLeast(1f)
            val ox = marginLeft
            val oy = marginTop

            fun baseX(i: Float) = if (n > 1) i / (n - 1) * plotW else plotW / 2f
            fun baseY(v: Float) = plotH - (v - yMin) / (yMax - yMin) * plotH
            fun sx(i: Float) = ox + baseX(i) * scale + offset.x
            fun sy(v: Float) = oy + baseY(v) * scale + offset.y
            fun screenXToIndex(px: Float): Float {
                val bx = (px - ox - offset.x) / scale
                return if (n > 1) bx / plotW * (n - 1) else 0f
            }
            fun screenYToAmp(py: Float): Float {
                val by = (py - oy - offset.y) / scale
                return yMin + (plotH - by) / plotH * (yMax - yMin)
            }

            if (n >= 1) {
                val iLeft = screenXToIndex(ox).coerceIn(0f, (n - 1).toFloat())
                val iRight = screenXToIndex(ox + plotW).coerceIn(0f, (n - 1).toFloat())
                val ampTop = screenYToAmp(oy)
                val ampBottom = screenYToAmp(oy + plotH)

                val xStep = niceStep(iRight - iLeft, 6)
                var xt = ceil(iLeft / xStep) * xStep
                while (xt <= iRight) {
                    val px = sx(xt)
                    drawLine(gridColor, Offset(px, oy), Offset(px, oy + plotH), 1f)
                    val m = textMeasurer.measure(xt.toLong().toString(), labelStyle)
                    drawText(m, topLeft = Offset(px - m.size.width / 2f, oy + plotH + 6f))
                    xt += xStep
                }

                val yStep = niceStep(ampTop - ampBottom, 6)
                var yt = ceil(ampBottom / yStep) * yStep
                while (yt <= ampTop) {
                    val py = sy(yt)
                    drawLine(gridColor, Offset(ox, py), Offset(ox + plotW, py), 1f)
                    val m = textMeasurer.measure(yt.toLong().toString(), labelStyle)
                    drawText(m, topLeft = Offset(ox - m.size.width - 6f, py - m.size.height / 2f))
                    yt += yStep
                }

                clipRect(ox, oy, ox + plotW, oy + plotH) {
                    val li = floor(iLeft).toInt().coerceIn(0, n - 1)
                    val ri = ceil(iRight).toInt().coerceIn(0, n - 1)
                    val visN = (ri - li).coerceAtLeast(1)
                    val step = max(1, visN / (plotW.toInt().coerceAtLeast(1) * 2))

                    // capture-boundary markers (thinned so they don't form a wall when zoomed out)
                    var lastBx = -1e9f
                    for (b in boundaries) {
                        if (b < li || b > ri) continue
                        val px = sx(b.toFloat())
                        if (px - lastBx < 6f) continue
                        drawLine(boundaryColor, Offset(px, oy), Offset(px, oy + plotH), 1f)
                        lastBx = px
                    }

                    for (ch in visible) {
                        val data = channelData[ch] ?: continue
                        val path = Path()
                        var first = true
                        var i = li
                        while (i <= ri) {
                            if (i < data.size) {
                                val px = sx(i.toFloat())
                                val py = sy(data[i].toFloat())
                                if (first) { path.moveTo(px, py); first = false } else path.lineTo(px, py)
                            }
                            i += step
                        }
                        if (ri < data.size && (ri - li) % step != 0) {
                            path.lineTo(sx(ri.toFloat()), sy(data[ri].toFloat()))
                        }
                        drawPath(path, color = channelColor(ch), style = Stroke(width = 2f))
                    }
                }
            }

            drawLine(axisColor, Offset(ox, oy), Offset(ox, oy + plotH), 2f)
            drawLine(axisColor, Offset(ox, oy + plotH), Offset(ox + plotW, oy + plotH), 2f)

            val xTitle = textMeasurer.measure("sample index (concatenated)", labelStyle)
            drawText(xTitle, topLeft = Offset(ox + plotW / 2f - xTitle.size.width / 2f, size.height - xTitle.size.height))
            val yTitle = textMeasurer.measure("amplitude", labelStyle)
            drawText(yTitle, topLeft = Offset(2f, oy - yTitle.size.height - 2f))
        }

        if (visible.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    when {
                        loading || checkedChannels.isNotEmpty() -> "Loading channels…"
                        else -> "No channels selected"
                    },
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        ChannelSelector(
            nChannels = nChannels,
            checkedChannels = checkedChannels,
            channelData = channelData,
            modifier = Modifier.align(Alignment.TopStart).padding(8.dp)
        ) { onToggleChannel(it) }

        TextButton(
            onClick = { scale = 1f; offset = Offset.Zero },
            modifier = Modifier.align(Alignment.BottomEnd).padding(4.dp)
        ) { Text("Fit") }
    }
}

@Composable
private fun ChannelSelector(
    nChannels: Int,
    checkedChannels: List<Int>,
    channelData: Map<Int, IntArray>,
    modifier: Modifier = Modifier,
    onToggle: (Int) -> Unit,
) {
    Column(
        modifier = modifier
            .background(
                MaterialTheme.colorScheme.surface.copy(alpha = 0.88f),
                RoundedCornerShape(6.dp)
            )
            .heightIn(max = 260.dp)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 8.dp, vertical = 4.dp)
    ) {
        Text(
            "Channels",
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.padding(bottom = 2.dp)
        )
        for (ch in 0 until nChannels) {
            val checked = checkedChannels.contains(ch)
            val loadingThis = checked && !channelData.containsKey(ch)
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.clickable { onToggle(ch) }
            ) {
                Checkbox(checked = checked, onCheckedChange = { onToggle(ch) })
                Box(modifier = Modifier.size(10.dp).background(channelColor(ch)))
                Spacer(Modifier.width(4.dp))
                Text("ch$ch", style = MaterialTheme.typography.bodySmall)
                if (loadingThis) {
                    Spacer(Modifier.width(6.dp))
                    CircularProgressIndicator(modifier = Modifier.size(12.dp), strokeWidth = 2.dp)
                }
            }
        }
    }
}

/** Round a raw axis range/target-count into a human-friendly 1/2/5·10^k step. */
private fun niceStep(range: Float, targetTicks: Int): Float {
    if (range <= 0f || targetTicks <= 0) return 1f
    val raw = range / targetTicks
    val mag = 10f.pow(floor(log10(raw.toDouble())).toFloat())
    val norm = raw / mag
    val niceNorm = when {
        norm < 1.5f -> 1f
        norm < 3f -> 2f
        norm < 7f -> 5f
        else -> 10f
    }
    return (niceNorm * mag).coerceAtLeast(1f)
}
