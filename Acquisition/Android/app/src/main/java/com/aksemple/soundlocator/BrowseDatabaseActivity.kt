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

    var selected by remember { mutableStateOf<CaptureListItem?>(null) }
    // Per-channel sample arrays for the selected capture, loaded lazily on demand.
    val channelData = remember { mutableStateMapOf<Int, IntArray>() }
    val checkedChannels = remember { mutableStateListOf<Int>() }
    var waveLoading by remember { mutableStateOf(false) }

    fun loadChannelAsync(captureId: Long, ch: Int) {
        if (channelData.containsKey(ch)) return
        scope.launch {
            try {
                val vals = withContext(Dispatchers.IO) {
                    db.soundDataDao().loadChannel(captureId, ch).map { it.value }.toIntArray()
                }
                // Ignore if the user moved on to another capture meanwhile.
                if (selected?.id == captureId) channelData[ch] = vals
            } catch (e: Exception) {
                android.util.Log.e("BrowseDatabase", "Failed to load channel $ch of capture $captureId", e)
            }
        }
    }

    fun selectCapture(item: CaptureListItem) {
        selected = item
        channelData.clear()
        checkedChannels.clear()
        val defaults = (0 until minOf(DEFAULT_VISIBLE_CHANNELS, item.nChannels)).toList()
        checkedChannels.addAll(defaults)
        waveLoading = true
        scope.launch {
            try {
                for (ch in defaults) {
                    val vals = withContext(Dispatchers.IO) {
                        db.soundDataDao().loadChannel(item.id, ch).map { it.value }.toIntArray()
                    }
                    if (selected?.id == item.id) channelData[ch] = vals
                }
            } catch (e: Exception) {
                android.util.Log.e("BrowseDatabase", "Failed to load default channels", e)
            } finally {
                if (selected?.id == item.id) waveLoading = false
            }
        }
    }

    fun toggleChannel(ch: Int) {
        val cap = selected ?: return
        if (checkedChannels.contains(ch)) {
            checkedChannels.remove(ch)
        } else {
            checkedChannels.add(ch)
            loadChannelAsync(cap.id, ch)
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
        // Left 2/3 - waveform + per-channel checkboxes
        Box(modifier = Modifier.weight(2f).fillMaxHeight()) {
            WaveformPane(
                selected = selected,
                channelData = channelData,
                checkedChannels = checkedChannels,
                loading = waveLoading,
                onToggleChannel = { toggleChannel(it) }
            )
        }
        VerticalDivider(
            modifier = Modifier.fillMaxHeight(),
            color = MaterialTheme.colorScheme.outlineVariant
        )
        // Right 1/3 - lazily loaded capture list
        Box(modifier = Modifier.weight(1f).fillMaxHeight()) {
            CaptureListPane(
                captures = captures,
                selectedId = selected?.id,
                isLoading = isLoading,
                endReached = endReached,
                onLoadMore = { loadNextPage() },
                onSelect = { selectCapture(it) }
            )
        }
    }
}

@Composable
private fun CaptureListPane(
    captures: List<CaptureListItem>,
    selectedId: Long?,
    isLoading: Boolean,
    endReached: Boolean,
    onLoadMore: () -> Unit,
    onSelect: (CaptureListItem) -> Unit,
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
            text = "Captures",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(12.dp)
        )
        HorizontalDivider()
        LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
            items(items = captures, key = { it.id }) { item ->
                CaptureRow(
                    item = item,
                    selected = item.id == selectedId,
                    onClick = { onSelect(item) }
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
private fun CaptureRow(item: CaptureListItem, selected: Boolean, onClick: () -> Unit) {
    val bg = if (selected) MaterialTheme.colorScheme.primaryContainer else Color.Transparent
    val perChannel = if (item.nChannels > 0) item.soundCount / item.nChannels else item.soundCount
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(bg)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp)
    ) {
        Text(
            text = dateFormat.format(Date(item.timestamp)),
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium
        )
        Spacer(Modifier.height(2.dp))
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

@Composable
private fun WaveformPane(
    selected: CaptureListItem?,
    channelData: Map<Int, IntArray>,
    checkedChannels: List<Int>,
    loading: Boolean,
    onToggleChannel: (Int) -> Unit,
) {
    if (selected == null) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                "Select a capture to view its waveform",
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        return
    }

    // Channels currently checked AND already loaded — those we actually plot.
    val visible = checkedChannels.filter { channelData.containsKey(it) }.sorted()
    val visibleKey = visible.joinToString(",")

    // n = samples per channel; y-range across all visible channels.
    val stats = remember(selected.id, visibleKey, channelData.size) {
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

    // Image-style transform; reset only when a different capture is selected.
    var scale by remember(selected.id) { mutableFloatStateOf(1f) }
    var offset by remember(selected.id) { mutableStateOf(Offset.Zero) }

    val textMeasurer = rememberTextMeasurer()
    val axisColor = MaterialTheme.colorScheme.outline
    val gridColor = MaterialTheme.colorScheme.outlineVariant
    val labelColor = MaterialTheme.colorScheme.onSurfaceVariant
    val labelStyle = TextStyle(color = labelColor, fontSize = 10.sp)

    Box(modifier = Modifier.fillMaxSize()) {
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .pointerInput(selected.id) {
                    detectTransformGestures { centroid, pan, zoom, _ ->
                        val newScale = (scale * zoom).coerceIn(0.25f, 500f)
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

                // vertical gridlines + sample-index labels
                val xStep = niceStep(iRight - iLeft, 6)
                var xt = ceil(iLeft / xStep) * xStep
                while (xt <= iRight) {
                    val px = sx(xt)
                    drawLine(gridColor, Offset(px, oy), Offset(px, oy + plotH), 1f)
                    val m = textMeasurer.measure(xt.toLong().toString(), labelStyle)
                    drawText(m, topLeft = Offset(px - m.size.width / 2f, oy + plotH + 6f))
                    xt += xStep
                }

                // horizontal gridlines + amplitude labels
                val yStep = niceStep(ampTop - ampBottom, 6)
                var yt = ceil(ampBottom / yStep) * yStep
                while (yt <= ampTop) {
                    val py = sy(yt)
                    drawLine(gridColor, Offset(ox, py), Offset(ox + plotW, py), 1f)
                    val m = textMeasurer.measure(yt.toLong().toString(), labelStyle)
                    drawText(m, topLeft = Offset(ox - m.size.width - 6f, py - m.size.height / 2f))
                    yt += yStep
                }

                // channel traces, clipped to the plot rect
                clipRect(ox, oy, ox + plotW, oy + plotH) {
                    val li = floor(iLeft).toInt().coerceIn(0, n - 1)
                    val ri = ceil(iRight).toInt().coerceIn(0, n - 1)
                    val visN = (ri - li).coerceAtLeast(1)
                    val step = max(1, visN / (plotW.toInt().coerceAtLeast(1) * 2))
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

            // axis frame
            drawLine(axisColor, Offset(ox, oy), Offset(ox, oy + plotH), 2f)
            drawLine(axisColor, Offset(ox, oy + plotH), Offset(ox + plotW, oy + plotH), 2f)

            // axis titles
            val xTitle = textMeasurer.measure("sample index", labelStyle)
            drawText(xTitle, topLeft = Offset(ox + plotW / 2f - xTitle.size.width / 2f, size.height - xTitle.size.height))
            val yTitle = textMeasurer.measure("amplitude", labelStyle)
            drawText(yTitle, topLeft = Offset(2f, oy - yTitle.size.height - 2f))
        }

        // Empty-state hint over the (still-drawn) axes
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

        // Channel checkbox list (overlay, top-start)
        ChannelSelector(
            nChannels = selected.nChannels,
            checkedChannels = checkedChannels,
            channelData = channelData,
            modifier = Modifier.align(Alignment.TopStart).padding(8.dp)
        ) { onToggleChannel(it) }

        // Reset-view control
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
